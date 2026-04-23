"""
Labor Reallocation Model
========================
Predicts where displaced workers are likely to transition when their occupation
is automated, by routing displaced supply through a skill-space transition matrix.

Mechanism:
  1. Supply  — each occupation contributes workers_at_risk = employment × displacement%
  2. Skill space — each occupation is mapped to a 3D vector:
       [physical orientation,  routine-cognitive,  interpersonal/creative-cognitive]
     This captures the two primary mobility constraints in the literature:
       - Physical ↔ cognitive orientation (hardest barrier to cross)
       - Routine cognitive ↔ interpersonal/creative cognitive (second barrier)
  3. Similarity — pairwise cosine similarity in skill space, plus a same-group
     affinity bonus (same SOC major group transitions are ~3× more probable;
     see Cortes et al. 2016, Del Rio-Chanona et al. 2020).
  4. Absorption — receiving jobs are down-weighted by (1 − displacement)² so
     workers don't pile into occupations that are also being automated.
  5. Routing — row-normalize the weighted similarity matrix to get a transition
     probability matrix T; inflow[j] = Σ_i supply[i] × T[i,j].

Outputs:
  Per occupation: outflow, inflow, net_flow, net_flow_pct
  Per group:      aggregate summary + group × group flow matrix (for Sankey)

References:
  Del Rio-Chanona et al. (2020). Supply and demand shocks in the labour market
    during the Covid-19 pandemic. Oxford Review of Economic Policy.
  Cortes et al. (2016). Disappearing routine jobs. Labour Economics.
"""

import numpy as np
import pandas as pd

SAME_GROUP_BONUS = 0.30   # cosine similarity boost for same SOC major group
ABSORPTION_POWER = 2.0    # exponent for absorption weight: (1 − displacement)^k


# ─── Skill space ─────────────────────────────────────────────────────────────

def _skill_vectors(df: pd.DataFrame) -> np.ndarray:
    """
    3D skill vector for each occupation:
      dim 0: phys_share / 100                     physical orientation
      dim 1: (1 − phys) × (ai_tech / 100)         routine-cognitive  (AI-replaceable)
      dim 2: (1 − phys) × (1 − ai_tech / 100)     interpersonal/creative-cognitive
    """
    phys = df['phys_share'].values / 100.0
    cog  = 1.0 - phys
    ai   = df['ai_tech'].values / 100.0
    return np.column_stack([phys, cog * ai, cog * (1.0 - ai)])


def _cosine_sim(v: np.ndarray) -> np.ndarray:
    norms = np.linalg.norm(v, axis=1, keepdims=True).clip(1e-10)
    return np.clip((v / norms) @ (v / norms).T, 0.0, 1.0)


def _transition_matrix(df: pd.DataFrame) -> np.ndarray:
    """Row-stochastic transition probability matrix (n × n)."""
    v   = _skill_vectors(df)
    sim = _cosine_sim(v)

    grps = df['group'].astype(str).str[:2].values
    sim  = np.clip(sim + SAME_GROUP_BONUS * (grps[:, None] == grps[None, :]), 0.0, 1.0)
    np.fill_diagonal(sim, 0.0)                                   # no self-routing

    absorb = (1.0 - df['displacement'].values / 100.0) ** ABSORPTION_POWER
    w      = sim * absorb[None, :]                               # (n, n)
    return w / w.sum(axis=1, keepdims=True).clip(1e-10)          # row-normalize


# ─── Occupation-level reallocation ───────────────────────────────────────────

def compute_reallocation(
    scores: pd.DataFrame,
    national_emp: "pd.Series | None" = None,
) -> pd.DataFrame:
    """
    Args:
        scores:       occupation scores (bls_automation_scores.csv)
        national_emp: optional Series keyed by soc → national employment count.
                      If None, all occupations get equal weight (relative mode).
    Returns:
        scores enriched with:
            national_employment, outflow, inflow, net_flow, net_flow_pct
    """
    df = scores.copy()
    df['soc'] = df['soc'].astype(str)

    if national_emp is not None:
        df['national_employment'] = df['soc'].map(national_emp).fillna(0.0)
    else:
        df['national_employment'] = 1.0

    df['outflow'] = df['national_employment'] * df['displacement'] / 100.0

    T      = _transition_matrix(df)
    inflow = df['outflow'].values @ T                            # (n,)

    df['inflow']       = inflow
    df['net_flow']     = inflow - df['outflow'].values
    df['net_flow_pct'] = (
        df['net_flow'] / df['national_employment'].replace(0.0, np.nan) * 100
    )

    for col in ['outflow', 'inflow', 'net_flow', 'national_employment']:
        df[col] = df[col].round(0)
    df['net_flow_pct'] = df['net_flow_pct'].round(1)

    return df


# ─── Group-level aggregation ─────────────────────────────────────────────────

def compute_group_summary(df_r: pd.DataFrame) -> pd.DataFrame:
    """Aggregate reallocation results to SOC major group level."""
    summary = (
        df_r
        .groupby(['group', 'group_name'], as_index=False)
        .agg(
            n_occupations    = ('soc',                  'count'),
            total_employment = ('national_employment',  'sum'),
            total_outflow    = ('outflow',               'sum'),
            total_inflow     = ('inflow',                'sum'),
            net_flow         = ('net_flow',              'sum'),
            avg_displacement = ('displacement',          'mean'),
        )
    )
    summary['net_flow_pct']      = (
        summary['net_flow'] / summary['total_employment'].replace(0.0, np.nan) * 100
    ).round(1)
    summary['avg_displacement']  = summary['avg_displacement'].round(1)
    for col in ['total_employment', 'total_outflow', 'total_inflow', 'net_flow']:
        summary[col] = summary[col].round(0).astype(int)

    return summary.sort_values('net_flow', ascending=False).reset_index(drop=True)


def compute_flow_matrix(df_r: pd.DataFrame) -> pd.DataFrame:
    """
    Returns a (group_name × group_name) DataFrame of worker flows.
    Entry [src, dst] = estimated workers moving from src group to dst group.
    Diagonal = within-group reallocation.
    """
    T      = _transition_matrix(df_r)
    supply = df_r['outflow'].values
    F      = supply[:, None] * T                                 # (n, n) occ-pair flows

    groups   = df_r['group'].astype(str).str[:2].values
    gn_map   = dict(zip(df_r['group'].astype(str).str[:2], df_r['group_name']))

    codes, uniq = pd.factorize(groups, sort=True)
    n_g         = len(uniq)
    ind         = np.eye(n_g)[codes]                             # (n, n_grps) indicator
    G           = (ind.T @ F @ ind).round(0)                     # (n_grps, n_grps)

    labels = [gn_map.get(g, g) for g in uniq]
    return pd.DataFrame(G, index=labels, columns=labels)
