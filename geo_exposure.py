#!/usr/bin/env python3
"""
Geographic Exposure Aggregator

Aggregates occupation-level automation scores (from bls_automation_scores.csv)
into region-level exposure indices using an employment-by-occupation matrix.

Input schema (employment_by_region.csv):
  - region_id (str)
  - soc (str, BLS SOC code like 15-1252)
  - employment (int/float)
  - region_name (optional)

Outputs:
  - geo_scores.csv with per-region indices:
      region_id, region_name, total_employment,
      displacement_index, raw_capability_index,
      ai_raw_index, robot_raw_index,
      ai_share_of_raw, robot_share_of_raw,
      threat_share_ai, threat_share_robotic, threat_share_both

Usage:
  python geo_exposure.py --employment employment_by_region.csv \
                         [--scores bls_automation_scores.csv] \
                         [--out geo_scores.csv]
"""

import argparse
import sys
import pandas as pd


def load_scores(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    required = {
        'soc', 'title', 'group', 'group_name', 'phys_share', 'ai_tech',
        'robot_tech', 'barrier', 'raw_capability', 'displacement', 'primary_threat'
    }
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Scores file is missing columns: {sorted(missing)}")
    # Ensure SOC codes are strings
    df['soc'] = df['soc'].astype(str)
    return df


def load_employment(path: str) -> pd.DataFrame:
    df = pd.read_csv(path)
    required = {'region_id', 'soc', 'employment'}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Employment file is missing columns: {sorted(missing)}")
    df['soc'] = df['soc'].astype(str)
    # normalize region_name presence
    if 'region_name' not in df.columns:
        df['region_name'] = df['region_id']
    return df


def compute_region_indices(df_join: pd.DataFrame) -> pd.DataFrame:
    # region totals & shares
    totals = df_join.groupby('region_id', as_index=False)['employment'].sum().rename(columns={'employment': 'total_employment'})
    df = df_join.merge(totals, on='region_id', how='left')
    df['emp_share'] = df['employment'] / df['total_employment']

    # Pre-barrier contributions
    df['robot_raw'] = (df['robot_tech'] * df['phys_share']) / 100.0
    df['ai_raw'] = (df['ai_tech'] * (100.0 - df['phys_share'])) / 100.0
    df['raw_capability_recalc'] = df['robot_raw'] + df['ai_raw']

    # Weighted sums per region
    agg = df.groupby(['region_id', 'region_name'], as_index=False).apply(
        lambda g: pd.Series({
            'total_employment': g['total_employment'].iloc[0],
            'displacement_index': (g['emp_share'] * g['displacement']).sum(),
            'raw_capability_index': (g['emp_share'] * g['raw_capability']).sum(),
            'ai_raw_index': (g['emp_share'] * g['ai_raw']).sum(),
            'robot_raw_index': (g['emp_share'] * g['robot_raw']).sum(),
            # Employment-weighted share of primary threat types
            'threat_share_ai': (g['emp_share'] * (g['primary_threat'] == 'AI').astype(float)).sum(),
            'threat_share_robotic': (g['emp_share'] * (g['primary_threat'] == 'Robotic').astype(float)).sum(),
            'threat_share_both': (g['emp_share'] * (g['primary_threat'] == 'Both').astype(float)).sum(),
        })
    ).reset_index(drop=True)

    # Shares of raw capability
    total_raw = agg['ai_raw_index'] + agg['robot_raw_index']
    agg['ai_share_of_raw'] = agg['ai_raw_index'] / total_raw.replace({0: pd.NA})
    agg['robot_share_of_raw'] = agg['robot_raw_index'] / total_raw.replace({0: pd.NA})

    # Round for readability (do not round total_employment)
    for col in ['displacement_index', 'raw_capability_index', 'ai_raw_index', 'robot_raw_index', 'ai_share_of_raw', 'robot_share_of_raw', 'threat_share_ai', 'threat_share_robotic', 'threat_share_both']:
        agg[col] = agg[col].astype(float).round(3)

    # Order columns
    cols = [
        'region_id', 'region_name', 'total_employment',
        'displacement_index', 'raw_capability_index',
        'ai_raw_index', 'robot_raw_index',
        'ai_share_of_raw', 'robot_share_of_raw',
        'threat_share_ai', 'threat_share_robotic', 'threat_share_both'
    ]
    return agg[cols]


def main(argv=None):
    p = argparse.ArgumentParser(description='Aggregate occupation scores into region exposure indices')
    p.add_argument('--employment', required=True, help='CSV with columns: region_id, soc, employment[, region_name]')
    p.add_argument('--scores', default='bls_automation_scores.csv', help='CSV of occupation scores (default: bls_automation_scores.csv)')
    p.add_argument('--out', default='geo_scores.csv', help='Output CSV path (default: geo_scores.csv)')
    args = p.parse_args(argv)

    scores = load_scores(args.scores)
    emp = load_employment(args.employment)

    # Join
    df_join = emp.merge(scores, on='soc', how='left', validate='many_to_one')
    missing = df_join['title'].isna().sum()
    if missing:
        missing_socs = emp.loc[emp['soc'].isin(df_join.loc[df_join['title'].isna(), 'soc'].unique()), 'soc'].unique()
        print(f"Warning: {missing} employment rows have SOCs not found in scores (unique SOCs: {len(missing_socs)}). They will be dropped.", file=sys.stderr)
        df_join = df_join[~df_join['title'].isna()].copy()

    if df_join.empty:
        raise SystemExit('No rows left after joining employment with scores. Check SOC codes.')

    # Compute and save
    out = compute_region_indices(df_join)
    out.to_csv(args.out, index=False)

    # Console summary
    print(f"✓ Aggregated {df_join['region_id'].nunique()} regions, {df_join.shape[0]} employment rows → {args.out}")
    # Show top 10 by displacement_index
    top = out.sort_values('displacement_index', ascending=False).head(10)
    with pd.option_context('display.max_rows', None, 'display.max_columns', None):
        print('\nTop regions by displacement_index:')
        print(top[['region_id','region_name','displacement_index','ai_share_of_raw','robot_share_of_raw']].to_string(index=False))


if __name__ == '__main__':
    main()
