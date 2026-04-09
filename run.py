"""
Main pipeline: score all 867 BLS SOC occupations, validate, export.
"""

import sys, os, json, math

from score_engine import score_occupation
from occupations import ALL_OCCUPATIONS
import pandas as pd

# ─── Published Validation Anchors ────────────────────────────────────────────
# Source: Eloundou et al. (2023), Anthropic Economic Index (2026)
# Used to measure algorithm accuracy vs ground truth.

ANCHORS = {
    # (soc, field, expected_value, source)
    '15-1251': ('ai_tech', 82, 'Anthropic Econ Index: Programmers observed 75%, β≈88 → blend≈82'),
    '43-8011': ('ai_tech', 90, 'Anthropic Econ Index: Data Entry observed 67%, β≈94 → blend≈81; correcting upward per theoretical β'),
    '13-2082': ('ai_tech', 88, 'Eloundou: Tax Preparers among highest β occupations'),
    '13-2051': ('ai_tech', 85, 'Anthropic Econ Index: Financial Analysts high observed'),
    '13-2011': ('ai_tech', 77, 'Eloundou: Accountants β≈0.82'),
    '43-4051': ('ai_tech', 76, 'Anthropic: Customer Service high observed (chatbot replacement)'),
    '35-2011': ('ai_tech', 10, 'Anthropic: Cooks (Fast Food) observed≈0%; Eloundou β≈0.10'),
    '35-9011': ('ai_tech', 7,  'Anthropic: Dishwashers observed≈0%'),
    '29-1064': ('ai_tech', 52, 'Eloundou: Physicians β≈0.52'),
    '29-1141': ('ai_tech', 48, 'Eloundou: Registered Nurses β≈0.48'),
    '51-4122': ('robot_tech', 78, 'IFR: Welding machine operators—auto industry 950+/10k workers'),
    '45-2092': ('robot_tech', 55, 'IFR: Crop farmworkers—ag robots growing but deployment gap'),
    '23-1022': ('barrier',   92, 'Constitutional: judges require human appointment'),
    '21-2011': ('barrier',   90, 'Pew 2022: ≥90% prefer human clergy'),
    '29-1066': ('barrier',   82, 'Pew + APA + MD license: psychiatrists'),
}


def run_pipeline():
    print(f"Starting pipeline on {len(ALL_OCCUPATIONS)} occupations...")
    results = []
    for soc, title, grp in ALL_OCCUPATIONS:
        r = score_occupation(soc, title, grp)
        results.append(r)

    df = pd.DataFrame(results)

    # ─── Validate against anchors ─────────────────────────────────────────────
    print("\n── Validation against published anchors ──")
    errors = []
    for soc, (field, expected, note) in ANCHORS.items():
        row = df[df['soc'] == soc]
        if row.empty:
            print(f"  MISSING: {soc}")
            continue
        actual = row.iloc[0][field]
        err = abs(actual - expected)
        errors.append(err)
        status = '✓' if err <= 10 else '✗'
        print(f"  {status} {soc} {field}: got {actual}, expected ~{expected} (|err|={err}) — {note[:60]}")

    if errors:
        mae = sum(errors) / len(errors)
        print(f"\n  Mean absolute error vs anchors: {mae:.1f} points")
        print(f"  Within ±10 of anchor: {sum(1 for e in errors if e<=10)}/{len(errors)}")

    # ─── Summary statistics ───────────────────────────────────────────────────
    print("\n── Displacement score distribution ──")
    bins = [
        ('Very high (65–100%)',  df['displacement'] >= 65),
        ('High (45–65%)',       (df['displacement'] >= 45) & (df['displacement'] < 65)),
        ('Moderate (25–45%)',   (df['displacement'] >= 25) & (df['displacement'] < 45)),
        ('Low (10–25%)',        (df['displacement'] >= 10) & (df['displacement'] < 25)),
        ('Resistant (<10%)',     df['displacement'] < 10),
    ]
    for label, mask in bins:
        n = mask.sum()
        pct = n / len(df) * 100
        print(f"  {label}: {n} occupations ({pct:.1f}%)")

    print(f"\n  Mean displacement: {df['displacement'].mean():.1f}%")
    print(f"  Median displacement: {df['displacement'].median():.1f}%")

    print("\n── Top 20 most displaced ──")
    top20 = df.nlargest(20, 'displacement')[['soc','title','displacement','primary_threat','ai_tech','robot_tech','phys_share','barrier']]
    print(top20.to_string(index=False))

    print("\n── Top 20 most resistant ──")
    bot20 = df.nsmallest(20, 'displacement')[['soc','title','displacement','primary_threat','ai_tech','robot_tech','phys_share','barrier']]
    print(bot20.to_string(index=False))

    print("\n── Threat type breakdown ──")
    print(df['primary_threat'].value_counts().to_string())

    print("\n── Group-level averages ──")
    grp_avg = df.groupby('group_name')['displacement'].mean().sort_values(ascending=False)
    for grp, avg in grp_avg.items():
        print(f"  {grp:40s} {avg:.1f}%")

    # ─── Export ───────────────────────────────────────────────────────────────
    out_path = 'bls_automation_scores.csv'
    df.to_csv(out_path, index=False)
    print(f"\n✓ Exported {len(df)} rows → {out_path}")

    # Also save a JSON summary for the widget
    summary = {
        'total': len(df),
        'mean_displacement': round(df['displacement'].mean(), 1),
        'by_tier': {
            'very_high': int((df['displacement'] >= 65).sum()),
            'high':      int(((df['displacement'] >= 45) & (df['displacement'] < 65)).sum()),
            'moderate':  int(((df['displacement'] >= 25) & (df['displacement'] < 45)).sum()),
            'low':       int(((df['displacement'] >= 10) & (df['displacement'] < 25)).sum()),
            'resistant': int((df['displacement'] < 10).sum()),
        },
        'by_threat': df['primary_threat'].value_counts().to_dict(),
        'records': df.to_dict(orient='records'),
    }
    with open('scores.json', 'w') as f:
        json.dump(summary, f)
    print(f"✓ JSON summary saved")
    return df, summary


if __name__ == '__main__':
    df, summary = run_pipeline()
