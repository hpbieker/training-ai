#!/usr/bin/env python3
"""Inspect EatMyRide / Garmin Carb Balancer developer data in Garmin FIT files."""

from __future__ import annotations

import argparse
import datetime as dt
import glob
import json
import math
import struct
from dataclasses import dataclass
from pathlib import Path
from typing import Any


FIT_EPOCH = dt.datetime(1989, 12, 31, tzinfo=dt.UTC)
EATMYRIDE_APP_ID = "fa9d9beb-870b-4924-bb73-df0f53b31a40"
EATMYRIDE_FIELD_NAMES = {"1marap", "2marap"}

BASE_TYPES: dict[int, tuple[str, int, str, Any]] = {
    0x00: ("enum", 1, "B", 0xFF),
    0x01: ("sint8", 1, "b", 0x7F),
    0x02: ("uint8", 1, "B", 0xFF),
    0x83: ("sint16", 2, "h", 0x7FFF),
    0x84: ("uint16", 2, "H", 0xFFFF),
    0x85: ("sint32", 4, "i", 0x7FFFFFFF),
    0x86: ("uint32", 4, "I", 0xFFFFFFFF),
    0x07: ("string", 1, None, 0),
    0x88: ("float32", 4, "f", math.nan),
    0x89: ("float64", 8, "d", math.nan),
    0x0A: ("uint8z", 1, "B", 0),
    0x8B: ("uint16z", 2, "H", 0),
    0x8C: ("uint32z", 4, "I", 0),
    0x0D: ("byte", 1, "B", None),
    0x8E: ("sint64", 8, "q", 0x7FFFFFFFFFFFFFFF),
    0x8F: ("uint64", 8, "Q", 0xFFFFFFFFFFFFFFFF),
    0x90: ("uint64z", 8, "Q", 0),
}


@dataclass
class FieldDef:
    number: int
    size: int
    base_type: int


@dataclass
class DevFieldDef:
    number: int
    size: int
    developer_index: int


@dataclass
class Definition:
    architecture: int
    global_message: int
    fields: list[FieldDef]
    developer_fields: list[DevFieldDef]

    @property
    def endian(self) -> str:
        return ">" if self.architecture == 1 else "<"


@dataclass
class EatMyRideSample:
    index: int
    timestamp: dt.datetime | None
    elapsed_seconds: float | None
    packet: int
    raw: bytes

    @property
    def value_u16_le(self) -> int:
        return self.raw[0] | (self.raw[1] << 8)


def main() -> None:
    parser = argparse.ArgumentParser(description="Inspect EatMyRide data in a Garmin FIT file.")
    parser.add_argument(
        "fit_file",
        nargs="?",
        help="Path to FIT file. Defaults to newest data/garmin/activities/*/activity.fit.",
    )
    parser.add_argument(
        "--last-window",
        default="60m",
        help="Window at end of activity for underfueling/depletion trend, e.g. 30m or 90m.",
    )
    parser.add_argument("--json", action="store_true", help="Print JSON instead of text.")
    args = parser.parse_args()

    fit_file = Path(args.fit_file) if args.fit_file else newest_fit_file()
    samples, descriptors = parse_fit_file(fit_file)
    result = summarize(samples, descriptors, fit_file, parse_duration(args.last_window))

    if args.json:
        print(json.dumps(result, indent=2, sort_keys=True))
    else:
        print_text(result)


def newest_fit_file() -> Path:
    candidates = [Path(path) for path in glob.glob("data/garmin/activities/*/activity.fit")]
    if not candidates:
        raise SystemExit("No FIT file found under data/garmin/activities/*/activity.fit")
    return max(candidates, key=lambda path: path.stat().st_mtime)


def parse_duration(value: str) -> float:
    text = value.strip().lower()
    if text.endswith("m"):
        return float(text[:-1]) * 60.0
    if text.endswith("h"):
        return float(text[:-1]) * 3600.0
    if text.endswith("s"):
        return float(text[:-1])
    return float(text)


def parse_fit_file(path: Path) -> tuple[list[EatMyRideSample], dict[str, Any]]:
    data = path.read_bytes()
    if len(data) < 14:
        raise ValueError(f"{path} is too small to be a FIT file")

    header_size = data[0]
    data_size = struct.unpack_from("<I", data, 4)[0]
    offset = header_size
    end = header_size + data_size
    definitions: dict[int, Definition] = {}
    developer_data: dict[int, dict[str, Any]] = {}
    field_descriptions: dict[tuple[int, int], dict[str, Any]] = {}
    samples: list[EatMyRideSample] = []
    first_timestamp: dt.datetime | None = None
    last_timestamp_by_local: dict[int, dt.datetime] = {}

    while offset < end:
        record_header = data[offset]
        offset += 1

        if record_header & 0x80:
            local_message = record_header & 0x03
            time_offset = (record_header >> 2) & 0x1F
            definition = definitions.get(local_message)
            if definition is None:
                raise ValueError(f"Compressed record before definition for local message {local_message}")
            base_time = last_timestamp_by_local.get(local_message)
            timestamp = base_time + dt.timedelta(seconds=time_offset) if base_time else None
            values, dev_values, offset = read_data_message(data, offset, definition)
            if timestamp is not None:
                last_timestamp_by_local[local_message] = timestamp
            maybe_add_sample(
                samples,
                local_message,
                definition,
                values,
                dev_values,
                developer_data,
                field_descriptions,
                first_timestamp,
                timestamp,
            )
            continue

        local_message = record_header & 0x0F
        is_definition = bool(record_header & 0x40)
        has_dev_fields = bool(record_header & 0x20)

        if is_definition:
            definition, offset = read_definition(data, offset, has_dev_fields)
            definitions[local_message] = definition
            continue

        definition = definitions.get(local_message)
        if definition is None:
            raise ValueError(f"Data record before definition for local message {local_message}")

        values, dev_values, offset = read_data_message(data, offset, definition)
        timestamp_raw = values.get(253)
        timestamp = fit_timestamp(timestamp_raw) if isinstance(timestamp_raw, int) else None
        if timestamp:
            last_timestamp_by_local[local_message] = timestamp
            if first_timestamp is None and definition.global_message == 20:
                first_timestamp = timestamp

        if definition.global_message == 207:
            update_developer_data(developer_data, values)
        elif definition.global_message == 206:
            update_field_description(field_descriptions, values)

        maybe_add_sample(
            samples,
            local_message,
            definition,
            values,
            dev_values,
            developer_data,
            field_descriptions,
            first_timestamp,
            timestamp,
        )

    descriptors = {
        "developer_data": developer_data,
        "field_descriptions": {
            f"{developer_index}:{field_number}": description
            for (developer_index, field_number), description in field_descriptions.items()
        },
    }
    return samples, descriptors


def read_definition(data: bytes, offset: int, has_dev_fields: bool) -> tuple[Definition, int]:
    offset += 1  # reserved
    architecture = data[offset]
    offset += 1
    endian = ">" if architecture == 1 else "<"
    global_message = struct.unpack_from(f"{endian}H", data, offset)[0]
    offset += 2
    field_count = data[offset]
    offset += 1
    fields: list[FieldDef] = []
    for _ in range(field_count):
        fields.append(FieldDef(data[offset], data[offset + 1], data[offset + 2]))
        offset += 3

    developer_fields: list[DevFieldDef] = []
    if has_dev_fields:
        dev_field_count = data[offset]
        offset += 1
        for _ in range(dev_field_count):
            developer_fields.append(DevFieldDef(data[offset], data[offset + 1], data[offset + 2]))
            offset += 3

    return Definition(architecture, global_message, fields, developer_fields), offset


def read_data_message(
    data: bytes, offset: int, definition: Definition
) -> tuple[dict[int, Any], list[tuple[DevFieldDef, bytes]], int]:
    values: dict[int, Any] = {}
    for field in definition.fields:
        raw = data[offset : offset + field.size]
        offset += field.size
        values[field.number] = decode_field(raw, field.base_type, definition.endian)

    dev_values: list[tuple[DevFieldDef, bytes]] = []
    for field in definition.developer_fields:
        raw = data[offset : offset + field.size]
        offset += field.size
        dev_values.append((field, raw))

    return values, dev_values, offset


def decode_field(raw: bytes, base_type: int, endian: str) -> Any:
    type_info = BASE_TYPES.get(base_type)
    if type_info is None:
        return raw
    name, size, fmt, invalid = type_info
    if name == "string":
        return raw.split(b"\x00", 1)[0].decode("utf-8", errors="ignore")
    if name == "byte" or fmt is None:
        return raw
    if len(raw) == size:
        value = struct.unpack(f"{endian}{fmt}", raw)[0]
        return None if value == invalid else value
    if len(raw) > size and len(raw) % size == 0:
        values = [
            struct.unpack(f"{endian}{fmt}", raw[index : index + size])[0]
            for index in range(0, len(raw), size)
        ]
        filtered = [value for value in values if value != invalid]
        return filtered
    return raw


def fit_timestamp(value: int | None) -> dt.datetime | None:
    if value is None:
        return None
    return FIT_EPOCH + dt.timedelta(seconds=value)


def update_developer_data(developer_data: dict[int, dict[str, Any]], values: dict[int, Any]) -> None:
    developer_index = values.get(3)
    developer_index = first_value(developer_index)
    if not isinstance(developer_index, int):
        return
    application_id = values.get(1)
    if isinstance(application_id, bytes):
        application_id_text = application_id.hex()
    else:
        application_id_text = None
    developer_data[int(developer_index)] = {
        "developer_index": developer_index,
        "application_id": format_uuid(application_id_text),
    }


def update_field_description(
    field_descriptions: dict[tuple[int, int], dict[str, Any]], values: dict[int, Any]
) -> None:
    developer_index = first_value(values.get(0))
    field_number = first_value(values.get(1))
    if not isinstance(developer_index, int) or not isinstance(field_number, int):
        return
    field_descriptions[(int(developer_index), int(field_number))] = {
        "developer_index": developer_index,
        "field_number": field_number,
        "field_name": values.get(3),
        "units": values.get(8),
        "fit_base_type_id": values.get(2),
    }


def first_value(value: Any) -> Any:
    if isinstance(value, list):
        return value[0] if value else None
    return value


def maybe_add_sample(
    samples: list[EatMyRideSample],
    local_message: int,
    definition: Definition,
    values: dict[int, Any],
    dev_values: list[tuple[DevFieldDef, bytes]],
    developer_data: dict[int, dict[str, Any]],
    field_descriptions: dict[tuple[int, int], dict[str, Any]],
    first_timestamp: dt.datetime | None,
    timestamp: dt.datetime | None,
) -> None:
    if definition.global_message != 20:
        return
    for field, raw in dev_values:
        description = field_descriptions.get((field.developer_index, field.number), {})
        app_id = developer_data.get(field.developer_index, {}).get("application_id")
        if (
            description.get("field_name") in EATMYRIDE_FIELD_NAMES
            or (app_id == EATMYRIDE_APP_ID and field.number == 132)
            or (field.developer_index == 4 and field.number == 132 and field.size == 4)
        ):
            elapsed = (timestamp - first_timestamp).total_seconds() if timestamp and first_timestamp else None
            samples.append(
                EatMyRideSample(
                    index=len(samples),
                    timestamp=timestamp,
                    elapsed_seconds=elapsed,
                    packet=raw[3] if len(raw) >= 4 else -1,
                    raw=raw,
                )
            )


def summarize(
    samples: list[EatMyRideSample],
    descriptors: dict[str, Any],
    fit_file: Path,
    last_window_seconds: float,
) -> dict[str, Any]:
    field_descriptor = find_eatmyride_descriptor(descriptors)
    field_name = field_descriptor.get("field_name") if field_descriptor else None
    by_packet: dict[int, list[EatMyRideSample]] = {}
    for sample in samples:
        by_packet.setdefault(sample.packet, []).append(sample)

    intake_events = [
        {
            "elapsed": format_elapsed(sample.elapsed_seconds),
            "product_code": f"{sample.raw[0]:02x}",
            "raw": sample.raw.hex(),
        }
        for sample in samples
        if len(sample.raw) >= 4 and sample.raw[1:] == b"\x8e\x02\x02"
    ]
    duration = max((sample.elapsed_seconds for sample in samples if sample.elapsed_seconds is not None), default=None)
    window_start = duration - last_window_seconds if duration is not None else None

    packet_summary: dict[str, Any] = {}
    for packet, packet_samples in sorted(by_packet.items()):
        first = first_numeric_sample(packet_samples)
        last = last_numeric_sample(packet_samples)
        window_first = (
            first_numeric_sample([s for s in packet_samples if s.elapsed_seconds is not None and s.elapsed_seconds >= window_start])
            if window_start is not None
            else None
        )
        packet_summary[f"{packet:02x}"] = {
            "samples": len(packet_samples),
            "first_u16": first.value_u16_le if first else None,
            "last_u16": last.value_u16_le if last else None,
            "delta_u16": (last.value_u16_le - first.value_u16_le) if first and last else None,
            "last_window_delta_u16": (
                last.value_u16_le - window_first.value_u16_le if last and window_first else None
            ),
        }

    looks_like_supported_field = field_name == "2marap" and len(packet_summary) <= 64
    warning = None
    if not looks_like_supported_field:
        if field_name == "1marap":
            warning = "This is 1marap, an older packed format. Use legacy_1marap instead of 2marap packets."
        else:
            warning = (
                "The developer field does not match the observed 2marap format. "
                "This FIT file may have stripped, rewritten or differently encoded developer data."
            )

    processed_intake_end_g = (
        scaled_packet_value(packet_summary, "01", scale=10.0) if looks_like_supported_field else None
    )
    processed_intake_window_g = (
        scaled_packet_delta(packet_summary, "01", scale=10.0) if looks_like_supported_field else None
    )
    burn_candidate_1c_end_g = (
        scaled_packet_value(packet_summary, "1c", scale=1.0) if looks_like_supported_field else None
    )
    burn_candidate_1c_window_g = (
        scaled_packet_delta(packet_summary, "1c", scale=1.0) if looks_like_supported_field else None
    )
    net_depletion_end_g = (
        round(burn_candidate_1c_end_g - processed_intake_end_g, 1)
        if burn_candidate_1c_end_g is not None and processed_intake_end_g is not None
        else None
    )
    net_depletion_window_g = (
        round(burn_candidate_1c_window_g - processed_intake_window_g, 1)
        if burn_candidate_1c_window_g is not None and processed_intake_window_g is not None
        else None
    )

    return {
        "fit_file": str(fit_file),
        "duration": format_elapsed(duration),
        "samples": len(samples),
        "field": field_descriptor,
        "intake_events": {
            "count": len(intake_events),
            "events": intake_events,
        },
        "packets": packet_summary,
        "legacy_1marap": decode_legacy_1marap(samples) if field_name == "1marap" else None,
        "glycogen_depletion_estimate": {
            "method": "packet 1c burn/depletion candidate minus packet 01 processed-intake candidate",
            "warning": warning,
            "processed_intake_01_g": processed_intake_end_g,
            "burn_candidate_1c_g": burn_candidate_1c_end_g,
            "net_depletion_end_g": net_depletion_end_g,
            "last_window": format_elapsed(last_window_seconds),
            "processed_intake_01_last_window_g": processed_intake_window_g,
            "burn_candidate_1c_last_window_g": burn_candidate_1c_window_g,
            "net_depletion_last_window_g": net_depletion_window_g,
        },
    }


def decode_legacy_1marap(samples: list[EatMyRideSample]) -> dict[str, Any] | None:
    """Decode the older 1marap field.

    Observed 1marap records pack two tenths-of-gram counters into four bytes:
    bytes 0-1 carry one counter, with bit 7 of byte 1 acting like a flag, while
    bytes 2-3 carry another counter. The exact labels are not yet verified.
    """

    usable = [sample for sample in samples if len(sample.raw) >= 4 and sample.raw[3] < 0x20]
    if not usable:
        return None

    first = usable[0]
    last = usable[-1]
    intake_candidate = legacy_1marap_low_counter(last.raw) / 10.0
    burn_candidate = legacy_1marap_high_counter(last.raw) / 10.0
    first_intake = legacy_1marap_low_counter(first.raw) / 10.0
    first_burn = legacy_1marap_high_counter(first.raw) / 10.0
    net_candidate = round((burn_candidate - first_burn) - (intake_candidate - first_intake), 1)

    return {
        "method": (
            "Experimental 1marap decode: bytes 0-1 with byte1 high bit masked as one "
            "tenths-of-grams counter, bytes 2-3 as another tenths-of-grams counter."
        ),
        "samples": len(usable),
        "excluded_non_counter_samples": len(samples) - len(usable),
        "counter_a_bytes_0_1_masked_g": round(intake_candidate - first_intake, 1),
        "counter_b_bytes_2_3_g": round(burn_candidate - first_burn, 1),
        "counter_b_minus_counter_a_g": net_candidate,
        "last_raw": last.raw.hex(),
        "warning": (
            "Counter labels are not verified. In Lillehammer-Oslo, counter A behaves like "
            "a roughly 60 g/h intake/target accumulator after the first part of the ride, "
            "while counter B behaves like a burn/depletion accumulator."
        ),
    }


def legacy_1marap_low_counter(raw: bytes) -> int:
    return raw[0] | ((raw[1] & 0x7F) << 8)


def legacy_1marap_high_counter(raw: bytes) -> int:
    return raw[2] | (raw[3] << 8)


def first_numeric_sample(samples: list[EatMyRideSample]) -> EatMyRideSample | None:
    return next((sample for sample in samples if len(sample.raw) >= 4), None)


def last_numeric_sample(samples: list[EatMyRideSample]) -> EatMyRideSample | None:
    return next((sample for sample in reversed(samples) if len(sample.raw) >= 4), None)


def scaled_packet_value(packet_summary: dict[str, Any], packet: str, scale: float) -> float | None:
    value = packet_summary.get(packet, {}).get("last_u16")
    return round(value / scale, 1) if value is not None else None


def scaled_packet_delta(packet_summary: dict[str, Any], packet: str, scale: float) -> float | None:
    value = packet_summary.get(packet, {}).get("last_window_delta_u16")
    return round(value / scale, 1) if value is not None else None


def find_eatmyride_descriptor(descriptors: dict[str, Any]) -> dict[str, Any] | None:
    for description in descriptors.get("field_descriptions", {}).values():
        if description.get("field_name") in EATMYRIDE_FIELD_NAMES:
            return description
    return None


def print_text(result: dict[str, Any]) -> None:
    estimate = result["glycogen_depletion_estimate"]
    print(f"FIT: {result['fit_file']}")
    print(f"Duration: {result['duration']}")
    print(f"EatMyRide samples: {result['samples']}")
    print(f"Intake events: {result['intake_events']['count']}")
    print()
    print("Glycogen depletion estimate")
    if estimate.get("warning"):
        print(f"  warning: {estimate['warning']}")
    print(f"  processed intake (01/10): {estimate['processed_intake_01_g']} g")
    print(f"  burn/depletion candidate (1c): {estimate['burn_candidate_1c_g']} g")
    print(f"  net depletion at end: {estimate['net_depletion_end_g']} g")
    print(f"  last {estimate['last_window']}:")
    print(f"    processed intake: {estimate['processed_intake_01_last_window_g']} g")
    print(f"    burn/depletion candidate: {estimate['burn_candidate_1c_last_window_g']} g")
    print(f"    net depletion change: {estimate['net_depletion_last_window_g']} g")
    print()
    print("Key packet endings")
    for packet in ["01", "1c", "00", "07", "08", "0b", "0d", "1b"]:
        summary = result["packets"].get(packet)
        if summary:
            print(
                f"  {packet}: last={summary['last_u16']} "
                f"delta={summary['delta_u16']} "
                f"last_window_delta={summary['last_window_delta_u16']}"
            )

    legacy = result.get("legacy_1marap")
    if legacy:
        print()
        print("Legacy 1marap estimate")
        print(f"  counter A, bytes 0-1 masked: {legacy['counter_a_bytes_0_1_masked_g']} g")
        print(f"  counter B, bytes 2-3: {legacy['counter_b_bytes_2_3_g']} g")
        print(f"  counter B - counter A: {legacy['counter_b_minus_counter_a_g']} g")
        print(f"  warning: {legacy['warning']}")


def format_uuid(hex_text: str | None) -> str | None:
    if not hex_text or len(hex_text) != 32:
        return hex_text
    return f"{hex_text[0:8]}-{hex_text[8:12]}-{hex_text[12:16]}-{hex_text[16:20]}-{hex_text[20:32]}"


def format_elapsed(seconds: float | None) -> str | None:
    if seconds is None:
        return None
    seconds_int = int(round(seconds))
    sign = "-" if seconds_int < 0 else ""
    seconds_int = abs(seconds_int)
    hours, remainder = divmod(seconds_int, 3600)
    minutes, secs = divmod(remainder, 60)
    return f"{sign}{hours}:{minutes:02d}:{secs:02d}"


if __name__ == "__main__":
    main()
