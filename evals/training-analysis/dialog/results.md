# Sol: vanlig analyse og oppfølging, 18. oktober 2026

Fire reelle samtaler med gpt-6.1-sol, medium: to ulike aktiviteter, hver kjørt to ganger. Første melding inneholdt bare aktivitets-ID. Modellen fant riktig aktivitet blant tre rådatamapper og brukte analysehjelperne selv. Ingen ferdig analysepakke, fasit eller svarformat var gitt. Oppfølgingen fortsatte med eksakt samme samtale-ID.

| Test | Bestått |
|---|---:|
| Første analyse | 2/4 |
| Oppdatering etter subjektiv rapport | 4/4 |
| Hele samtalen | 2/4 |
| Riktig samtale videreført / opprinnelige filer uendret | 4/4 |

Begge Moss–Horten-analysene bestod. Begge førstesvarene for den korte Tanum-turen feilet fordi de konkluderte med «lett sykkeltur» før opplevd anstrengelse var kjent. Senere forbehold om ukjent restitusjon opphever ikke den for bastante hovedkonklusjonen. Lav målt ytre belastning må skilles tydelig fra en tur som oppleves lett.

Alle fire oppfølgingene endret vurderingen meningsfullt. Sol lot tung opplevelse veie tyngre enn lave gjennomsnitt eller Xerts vanskelighetsmerking, bevarte skillet mellom forholdsvis gode bein og tung pust, og stilte ikke en fysiologisk diagnose. Allerede forsiktige råd behøvde ikke reverseres for at oppdateringen skulle bestå.

Uavhengig kontroll fant ingen vesentlige tallfeil i stikkprøvene og bekreftet riktig aktivitet, råkilder og ferske hjelpeanalyser. Mindre svakheter: for omfattende førstesvar på kortturene, ett unøyaktig tilbakeblikk på egen formulering, og en formulering som kobler Xert Difficulty for tett til restitusjonsbehov. Ett korttur-svar identifiserte manglende opplevd anstrengelse uten å stille et spørsmål.

## Neste endring

Prioriter hovedkonklusjonen før subjektiv rapport: beskriv målt dose og struktur, men la opplevd letthet være åpen. Retest begge korttur-dialogene etter en avgrenset endring, med langturene som regresjonskontroll. Ingen nye coachingregler er endret i denne testrunden.

## Avgrensning og sporbarhet

Dette tester lokal rådatauthenting, beregning, fri norsk analyse og samtaleoppfølging. Live-integrasjoner, synkronisering og hele produksjonsmiljøet er ikke testet. Fire samtaler er et lite utvalg, ikke et generelt estimat av modellkvalitet. Kortturens subjektive oppfølging er syntetisk og er ikke lagret som historisk treningsinformasjon. Langturens rapport gjengir brukerens faktiske beskrivelse.

Førstesvarene tok 63–133 sekunder og var 398–475 ord; oppfølgingene tok 13–16 sekunder og var 159–189 ord. Det er rom for kortere analyser, særlig på korte turer.

- [Eksakte svar, kommandoer og hasher](results.json)
- [Uavhengig vurdering og kontrollerte tall](independent-review.json)
- [Testtilfeller og krav](cases.json)
- [Kjøring og metode](README.md)

Rå snapshots, CLI-hendelser og genererte artefakter er arkivert under `outputs/training-analysis-eval/2026-10-18-dialog/`. Originale kjørestier beholdes i loggene. Filhash-kontrollen gjelder opprinnelige filer i hver testkopi; nye analysefiler var tillatt. Brukstall fra CLI beholdes som rapportert og summeres ikke mellom første tur og resume, siden tellerne kan være kumulative.
