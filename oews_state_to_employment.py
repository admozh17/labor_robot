#!/usr/bin/env python3
"""
Convert BLS OEWS State workbook (e.g., state_M2024_dl.xlsx) into
employment_by_region.csv for the geo_exposure aggregator.

Input (Excel):
  - Columns typically include: AREA_TITLE, OCC_CODE, O_GROUP, TOT_EMP
  - One row per (state, occupation). We keep only detailed occupations.

Usage:
  python oews_state_to_employment.py --xlsx state_M2024_dl.xlsx \
                                     --out employment_by_region.states.csv

Notes:
  - If the workbook contains multiple sheets, the first sheet is used.
  - Non-numeric or suppressed employment (e.g., '*') are treated as missing and dropped.
  - Region IDs are state USPS abbreviations derived from AREA_TITLE.
"""

import argparse
import sys
import re
import pandas as pd

STATE_ABBR = {
    'alabama':'AL','alaska':'AK','arizona':'AZ','arkansas':'AR','california':'CA','colorado':'CO',
    'connecticut':'CT','delaware':'DE','district of columbia':'DC','florida':'FL','georgia':'GA',
    'hawaii':'HI','idaho':'ID','illinois':'IL','indiana':'IN','iowa':'IA','kansas':'KS','kentucky':'KY',
    'louisiana':'LA','maine':'ME','maryland':'MD','massachusetts':'MA','michigan':'MI','minnesota':'MN',
    'mississippi':'MS','missouri':'MO','montana':'MT','nebraska':'NE','nevada':'NV','new hampshire':'NH',
    'new jersey':'NJ','new mexico':'NM','new york':'NY','north carolina':'NC','north dakota':'ND',
    'ohio':'OH','oklahoma':'OK','oregon':'OR','pennsylvania':'PA','puerto rico':'PR','rhode island':'RI',
    'south carolina':'SC','south dakota':'SD','tennessee':'TN','texas':'TX','utah':'UT','vermont':'VT',
    'virginia':'VA','washington':'WA','west virginia':'WV','wisconsin':'WI','wyoming':'WY'
}

def norm_cols(df: pd.DataFrame) -> pd.DataFrame:
    cmap = {c.lower().strip(): c for c in df.columns}
    # Try to locate expected columns under various casings
    def pick(*names):
        for n in names:
            if n in cmap:
                return cmap[n]
        raise KeyError(f"Missing expected column among {names}")
    cols = {
        'area_title': pick('area_title','state','area name','area'),
        'occ_code': pick('occ_code','occupation code','soc_code','soc code'),
        'o_group': pick('o_group','occupation group','group'),
        'tot_emp': pick('tot_emp','employment','tot emp','total employment')
    }
    return df.rename(columns={v:k for k,v in cols.items()})

def to_abbr(area_title: str) -> str:
    s = (area_title or '').strip().lower()
    s = re.sub(r'\s+state$', '', s)
    return STATE_ABBR.get(s, s.upper()[:2])

def main(argv=None):
    ap = argparse.ArgumentParser(description='Convert OEWS State workbook to employment_by_region.csv format')
    ap.add_argument('--xlsx', required=True, help='Path to state_M20YY_dl.xlsx (from BLS OEWS)')
    ap.add_argument('--out', default='employment_by_region.states.csv', help='Output CSV path')
    args = ap.parse_args(argv)

    xls = pd.ExcelFile(args.xlsx)
    df = xls.parse(xls.sheet_names[0])
    df = norm_cols(df)

    # Keep detailed occupations only
    df = df[df['o_group'].str.lower().eq('detailed')].copy()

    # Clean employment values
    df['employment'] = pd.to_numeric(df['tot_emp'], errors='coerce')
    df = df.dropna(subset=['employment'])
    df = df[df['employment'] > 0]

    # Region id/name
    df['region_id'] = df['area_title'].map(to_abbr)
    df['region_name'] = df['area_title']

    out = df[['region_id','region_name','occ_code','employment']].rename(columns={'occ_code':'soc'})
    out.to_csv(args.out, index=False)
    print(f"✓ Wrote {len(out):,} rows across {out['region_id'].nunique()} states → {args.out}")

if __name__ == '__main__':
    main()

