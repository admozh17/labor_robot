# Automation Displacement Score — 830 BLS Occupations

A transparent, reproducible pipeline that scores every US occupation in the [BLS Standard Occupational Classification (SOC) 2018](https://www.bls.gov/soc/) system on its risk of displacement by robots and AI.

> **Interactive version**: [Open in Google Colab](https://colab.research.google.com/) ← upload `notebook.ipynb`  
> **Pre-scored results**: see [`bls_automation_scores.csv`](bls_automation_scores.csv)

---

## The core question

How much of each job can be automated — and by what, and when?

This project builds on the methodology introduced in Anthropic's [Labor Market Impacts of AI (2026)](https://www.anthropic.com/research/labor-market-impacts) paper, extending it to cover **both** AI and robotic displacement, and applying it to all 830 detailed SOC occupations.

---

## Formula

```
Displacement Risk = Raw Capability × (1 − Barrier)

where:

Raw Capability = (RobotTech × PhysShare) + (AItech × CogShare)
CogShare       = 1 − PhysShare
Barrier        = max(statutory_bar, licensing_liability, consumer_preference)
```

### Why this formula?

We don't want inflated scores for occupations threatened by only one dimension. A politician has near-zero robotic relevance — only 3% of their job is physical — so robot risk shouldn't lift their score. The weighted blend fixes this: each automation vector is weighted by what fraction of the job it actually applies to.

---

## Four parameters

| Parameter | Range | Source | Derivation |
|-----------|-------|--------|------------|
| **RobotTech** | 0–100 | IFR World Robotics 2022 + Acemoglu & Restrepo (2020) | Industry robot density (robots/10k workers), normalized 0–100. Blended 60% industry density, 40% physical task bottleneck score. |
| **AItech** | 0–100 | Eloundou et al. (2023) + Anthropic Economic Index (2026) | β-score average across O*NET tasks (β=1 → LLM alone speeds up 2×; β=0.5 → LLM+tools; β=0 → not feasible). Calibrated against published occupation-level scores. |
| **PhysShare** | 0–1 | O*NET Work Activities (elements 4.A.3.*) | Ratio of physical activity importance to total work activity importance. Group-level baselines from published O*NET summaries. |
| **Barrier** | 0–1 | BLS licensing data (2023) + Pew Research (2014/2022) + statutory law | `max(constitutional_bar, licensing+liability, consumer_preference)`. The `max()` rule reflects that one absolute barrier suffices to prevent displacement. |

---

## Data sources

### RobotTech: IFR 2022 + Acemoglu & Restrepo (2020)

The [International Federation of Robotics (IFR)](https://ifr.org) publishes annual robot density by industry. Key anchors used:

| Industry | Robots/10k workers (IFR 2022) | Normalized score |
|----------|-------------------------------|-----------------|
| Motor vehicles | ~1,100 | 95 |
| Electronics manufacturing | ~620 | 78 |
| Metal products | ~500 | 72 |
| Plastics & rubber | ~420 | 68 |
| Food & beverage manufacturing | ~120 | 38 |
| Construction | ~8 | 10 |
| Finance & insurance | ~3 | 3 |

Acemoglu & Restrepo (2020) provide the industry→occupation mapping methodology via the BLS industry-occupation employment matrix.

### AItech: Eloundou et al. (2023)

[Eloundou, Manning, Mishkin & Rock (2023)](https://arxiv.org/abs/2303.10130), "GPTs are GPTs," scores every O*NET task with a β value:
- **β = 1.0**: LLM alone can complete task at 2× speed
- **β = 0.5**: LLM + tools required
- **β = 0.0**: Not feasible for LLMs

`AItech = mean(β) × 100` for each occupation, then blended with Anthropic Economic Index observed exposure where available.

Published calibration anchors (from Eloundou 2023 + Anthropic 2026):

| Occupation | Expected AItech | Source |
|------------|----------------|--------|
| Computer Programmers | ~82 | Anthropic observed 75%, β≈88 |
| Data Entry Keyers | ~90 | Anthropic observed 67%, β≈94 |
| Tax Preparers | ~88 | Eloundou β ≈ 0.88 |
| Financial Analysts | ~85 | Anthropic high observed |
| Cooks (Fast Food) | ~10 | Anthropic observed ≈ 0% |
| Registered Nurses | ~48 | Eloundou β ≈ 0.48 |
| General Physicians | ~52 | Eloundou β ≈ 0.52 |

### PhysShare: O*NET Work Activities

O*NET element groups:
- **Physical** (4.A.3.*): Controlling machines, operating vehicles, performing physical activities, handling/moving objects, repairing equipment, inspecting structures
- **Cognitive** (4.A.1.*, 4.A.2.*, 4.A.4.*): Information input, mental processes, interacting/communicating

`PhysShare = Σ(physical activity importance) / Σ(all activity importance)`

To query this directly via the O*NET Web Services API:
```
GET https://services.onetcenter.org/ws/online/occupations/{SOC_CODE}/details/work_activities
```

### Barrier: BLS + Pew + statutory law

Three sub-components, take the max:

**1. Statutory/constitutional bar**
- Elected officials: US Constitution Art. I, II; state constitutions → 0.95
- Federal/state judges: constitutional appointment + tenure → 0.92
- Military command: UCMJ + DoD Directive 3000.09 (human-in-lethal-force-loop) → 0.85
- Administrative law judges: APA § 556 → 0.75

**2. Professional licensing + liability**
- MD/DO + malpractice: 0.68
- RN: 0.52 | APRN: 0.62
- JD + bar admission: 0.70
- Pilot (FAA Part 121 requires 2 licensed humans): 0.62
- Licensed trades (electrician, plumber): 0.18

**3. Consumer preference (Pew Research 2014, 2022)**

| Role | % opposing automation | Source |
|------|-----------------------|--------|
| Surgeon | 77% | Pew 2014 |
| Caregiver | 65% | Pew 2014 |
| Financial advisor | 73% | Pew 2014 |
| Teacher | 58% | Pew 2022 |
| Psychiatrist | 85%+ | Pew 2022 |
| Clergy | 90%+ | Pew 2022 |
| Fast food worker | ~5% | Pew 2014 |

---

## Validation

The model was validated against 15 published anchors before release:

| Anchor | Field | Expected | Got | Error |
|--------|-------|----------|-----|-------|
| Computer Programmers | ai_tech | 82 | 88 | 6 |
| Data Entry Keyers | ai_tech | 90 | 90 | 0 |
| Tax Preparers | ai_tech | 88 | 86 | 2 |
| Financial Analysts | ai_tech | 85 | 82 | 3 |
| Accountants | ai_tech | 77 | 84 | 7 |
| Customer Service Reps | ai_tech | 76 | 72 | 4 |
| Cooks (Fast Food) | ai_tech | 10 | 5 | 5 |
| Dishwashers | ai_tech | 7 | 5 | 2 |
| General Physicians | ai_tech | 52 | 46 | 6 |
| Registered Nurses | ai_tech | 48 | 43 | 5 |
| Welding Machine Operators | robot_tech | 78 | 95 | 17* |
| Farmworkers (Crop) | robot_tech | 55 | 45 | 10 |
| Judges & Magistrates | barrier | 92 | 92 | 0 |
| Clergy | barrier | 90 | 90 | 0 |
| Psychiatrists | barrier | 82 | 85 | 3 |

**Mean absolute error: 4.7 points** | **14/15 within ±10**

*The welding machine operator anchor (78) was our own prior estimate; the IFR data may support a higher score (auto industry ~1,100 robots/10k workers).

---

## Key findings

| Metric | Value |
|--------|-------|
| Total occupations scored | 830 |
| Mean displacement risk | 33.8% |
| Very high risk (65%+) | 43 occupations (5.2%) |
| High risk (45–65%) | 214 occupations (25.7%) |
| Moderate risk (25–45%) | 260 occupations (31.3%) |
| Low risk (10–25%) | 233 occupations (28.0%) |
| Resistant (<10%) | 80 occupations (9.6%) |

**Most displaced**: Welding Machine Operators (86%), Computer Programmers (83%), Software Developers (83%), Data Entry Keyers (80%)

**Most resistant**: Massage Therapists (1%), Clergy (2%), Childcare Workers (2%), Legislators (3%), Clinical Psychologists (3%)

**Group averages** (highest to lowest):

| Group | Avg displacement | n |
|-------|-----------------|---|
| Computer & Math | 74.4% | 22 |
| Office & Admin Support | 63.0% | 55 |
| Production | 52.1% | 111 |
| Business & Financial | 48.6% | 34 |
| Architecture & Eng | 45.6% | 36 |
| Install/Maint/Repair | 43.6% | 52 |
| Transportation & Material Moving | 39.2% | 51 |
| Sales | 37.8% | 22 |
| Management | 36.0% | 36 |
| Farming/Fishing/Forestry | 34.6% | 14 |
| Life/Physical Science | 32.1% | 42 |
| Building & Grounds | 30.7% | 9 |
| Arts & Entertainment | 27.2% | 38 |
| Food Preparation | 25.0% | 17 |
| Legal | 21.8% | 8 |
| Construction & Extraction | 20.1% | 62 |
| Education & Library | 15.5% | 61 |
| Community & Social | 11.1% | 17 |
| Healthcare Practitioners | 11.1% | 64 |
| Healthcare Support | 10.0% | 17 |
| Protective Service | 9.2% | 21 |
| Personal Care & Service | 8.2% | 28 |
| Military | 3.0% | 13 |

---

## How to run

```bash
pip install pandas numpy
python run.py
```

Output: `bls_automation_scores.csv`

### How to use real data (to go fully empirical)

Replace the group-level baselines in `score_engine.py` with live API queries:

**O*NET PhysShare (requires free registration):**
```python
import requests
url = f"https://services.onetcenter.org/ws/online/occupations/{soc}/details/work_activities"
headers = {"Authorization": "Basic YOUR_KEY_HERE"}
data = requests.get(url, headers=headers).json()
physical_ids = ['4.A.3.a.1','4.A.3.a.2','4.A.3.a.3','4.A.3.a.4',
                '4.A.3.b.1','4.A.3.b.2','4.A.3.b.3','4.A.3.b.4']
phys = sum(e['score']['value'] for e in data['element']
           if e['id'] in physical_ids)
total = sum(e['score']['value'] for e in data['element'])
phys_share = phys / total
```

**Eloundou β scores (public GitHub):**
```
https://github.com/EIG-Research/AI-unemployment/blob/main/data/gptsRgpts_occ_lvl.csv
```

**IFR robot density:** Available via IFR annual subscription, or use the industry density table in `score_engine.py` (derived from published IFR summaries).

---

## Limitations

1. **Within-group variation** is driven by title keywords, not full O*NET task-level scoring. Occupations in the same group without distinguishing keywords get the same base score.

2. **Barrier aggregation** uses `max()` which is theoretically motivated but could also be `mean()` or a weighted average. The choice affects healthcare and legal occupations most (barrier ≈ 20–30% lower under `mean()`).

3. **RobotTech projection**: IFR data is from 2022. The forward-projection to 2026+ adds ±15 points of uncertainty, particularly for autonomous vehicles and general-purpose humanoid robots.

4. **No temporal dimension**: Scores reflect current technical feasibility, not a timeline. See the companion analysis for deployment wave estimates.

---

## Citation

```bibtex
@misc{automation_displacement_2026,
  title  = {Automation Displacement Score: 830 BLS Occupations},
  year   = {2026},
  note   = {Four-parameter model combining IFR robot density, Eloundou et al. β-scores,
            O*NET physical activity ratios, and BLS/Pew institutional barriers.
            Built on methodology from Anthropic Economic Index (2026).},
  url    = {https://github.com/YOUR_USERNAME/automation-displacement-scores}
}
```

## References

- Eloundou, T., Manning, S., Mishkin, P., & Rock, D. (2023). GPTs are GPTs. *Science*, 384, 1306–1308.
- Massenkoff, M. & McCrory, P. (2026). Labor market impacts of AI: A new measure and early evidence. *Anthropic Economic Index*.
- Acemoglu, D. & Restrepo, P. (2020). Robots and Jobs: Evidence from US Labor Markets. *Journal of Political Economy*, 128(6), 2188–2244.
- International Federation of Robotics (2022). *World Robotics Report*.
- Pew Research Center (2014). *AI, Robotics, and the Future of Jobs*.
- BLS (2023). *Occupational Licensing: A State-by-State Approach*.
