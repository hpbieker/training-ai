"""Bounded, order-preserving geometric comparison; no road identity inference."""
import math
from collections import defaultdict

TOLERANCE_M = 2.0
MAX_POINTS = 250000
MAX_PAIRS = 2000000


def decode_polyline(data):
    result=[];index=0;current=[0,0]
    while index<len(data):
        for axis in range(2):
            value=0;shift=0
            while True:
                if index>=len(data) or shift>35: raise ValueError('Invalid polyline')
                byte=ord(data[index])-63;index+=1
                if not 0<=byte<=63: raise ValueError('Invalid polyline')
                value|=(byte&31)<<shift;shift+=5
                if byte<32: break
            current[axis]+=~(value>>1) if value&1 else value>>1
        lat,lon=(v/1e5 for v in current)
        if not (-90<=lat<=90 and -180<=lon<=180): raise ValueError('Invalid polyline coordinates')
        result.append((lat,lon))
        if len(result)>MAX_POINTS: raise ValueError('Point limit exceeded')
    if len(result)<2: raise ValueError('Polyline needs two points')
    return result


def compare_lines(expected, actual, tolerance_m=TOLERANCE_M):
    """Sparse discrete Frechet reachability on <= tolerance/2 metre samples.

    A monotone discrete matching provides a continuous matching within the same
    tolerance by linear interpolation. Rejection can still be inconclusive
    near the boundary because of the finite sampling interval.
    """
    if not math.isfinite(tolerance_m) or tolerance_m<=0: raise ValueError('Invalid tolerance')
    base={'status':'unresolved','tolerance_m':tolerance_m,'method':'ordered_sample_reachability',
          'road_identity_verified':False}
    try:
        if len(expected)<2 or len(actual)<2: raise ValueError('Insufficient geometry')
        lat0,lon0=expected[0];scale=math.cos(math.radians(lat0))
        def project(line):
            out=[]
            for lat,lon in line:
                if not all(math.isfinite(v) for v in (lat,lon)) or abs(lat-lat0)>3 or abs(lon-lon0)>3 or abs(lat)>80:
                    raise ValueError('Unsupported or invalid coordinate extent')
                out.append(((lon-lon0)*111195*scale,(lat-lat0)*111195))
            return out
        A,B=project(expected),project(actual)
        if expected==actual:return {**base,'status':'exact','max_matching_distance_m':0}
        def resample(line):
            out=[line[0]];length=0
            for a,b in zip(line,line[1:]):
                distance=math.dist(a,b);length+=distance;n=max(1,math.ceil(distance/(tolerance_m/2)))
                if len(out)+n>MAX_POINTS: raise ValueError('Sample limit exceeded')
                out.extend(tuple(a[k]+(b[k]-a[k])*i/n for k in range(2)) for i in range(1,n+1))
            return out,length
        a,la=resample(A);b,lb=resample(B);base.update(expected_length_m=round(la,2),actual_length_m=round(lb,2))
        radius=tolerance_m;grid=defaultdict(list)
        for j,p in enumerate(b):grid[math.floor(p[0]/radius),math.floor(p[1]/radius)].append(j)
        previous=set();pairs=0;furthest=0
        for i,p in enumerate(a):
            x,y=math.floor(p[0]/radius),math.floor(p[1]/radius);candidates=[]
            for dx in (-1,0,1):
                for dy in (-1,0,1):candidates.extend(grid.get((x+dx,y+dy),[]))
            pairs+=len(candidates)
            if pairs>MAX_PAIRS:raise ValueError('Comparison pair limit exceeded')
            reachable=set()
            for j in sorted(candidates):
                gap=math.dist(p,b[j])
                if gap<=radius and ((i==0 and j==0) or j in previous or j-1 in previous or j-1 in reachable):
                    reachable.add(j);furthest=max(furthest,j)
            if not reachable:
                # An order failure can be a small tolerance-edge discrepancy. Do
                # not claim a changed road without evidence outside tolerance.
                wide=[]
                for dx in (-3,-2,-1,0,1,2,3):
                    for dy in (-3,-2,-1,0,1,2,3):wide.extend(grid.get((x+dx,y+dy),[]))
                nearest=min((math.dist(p,b[j]) for j in wide),default=math.inf)
                changed=nearest>tolerance_m+radius
                return {**base,'status':'changed' if changed else 'unresolved',
                        'reason':'geometry_outside_tolerance' if changed else 'order_or_tolerance_mismatch',
                        'deviation':{'expected_location':{'lat':lat0+p[1]/111195,'lng':lon0+p[0]/(111195*scale)},
                                     'expected_sample':i,'actual_progress_sample':furthest,
                                     'nearest_sample_distance_m':round(nearest,2) if math.isfinite(nearest) else None}}
            previous=reachable
        if len(b)-1 not in previous:
            return {**base,'status':'changed','reason':'unmatched_saved_tail',
                    'deviation':{'actual_location':{'lat':actual[-1][0],'lng':actual[-1][1]}}}
        return {**base,'status':'equivalent_within_tolerance','max_matching_distance_m':tolerance_m}
    except (ValueError,TypeError,OverflowError) as exc:
        return {**base,'reason':str(exc)}


def compare_route_geometry(expected, actual):
    reports=[]
    try:
        left=expected['legs'];right=actual['legs']
        if len(left)!=len(right):return {'status':'unresolved','reason':'leg_structure_changed','expected_legs':len(left),'actual_legs':len(right)}
        for i,(a,b) in enumerate(zip(left,right)):
            ap=[p['polyline'] for p in a['paths']];bp=[p['polyline'] for p in b['paths']]
            if ap==bp:reports.append({'leg':i,'status':'exact'});continue
            def flatten(paths):
                coords=[]
                for p in paths:
                    if p['encoding']!='Google':raise ValueError('Unsupported polyline encoding')
                    line=decode_polyline(p['data'])
                    if coords and coords[-1]!=line[0]:raise ValueError('Discontinuous paths')
                    coords.extend(line if not coords else line[1:])
                return coords
            reports.append({'leg':i,**compare_lines(flatten(ap),flatten(bp))})
        status='changed' if any(r['status']=='changed' for r in reports) else 'unresolved' if any(r['status']=='unresolved' for r in reports) else 'exact' if all(r['status']=='exact' for r in reports) else 'equivalent_within_tolerance'
        return {'status':status,'tolerance_m':TOLERANCE_M,'legs_checked':len(reports),
                'non_exact_legs':[r for r in reports if r['status']!='exact'][:10],
                'non_exact_leg_count':sum(r['status']!='exact' for r in reports),'road_identity_verified':False}
    except (ValueError,KeyError,TypeError) as exc:
        return {'status':'unresolved','reason':'incomplete_or_invalid_geometry'}
