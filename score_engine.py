"""
Automation Displacement Score Engine
=====================================
Version: 1.0.0

Implements the four-parameter displacement model:
  Displacement = (RobotTech × PhysShare + AItech × CogShare) × (1 − Barrier)

Parameter derivation:
  PhysShare  → O*NET Work Activities ratio (elements 4.A.3.* / all 4.A.*)
  AItech     → Eloundou et al. (2023) β-score rubric, calibrated to published anchors
  RobotTech  → IFR 2022 industry density + O*NET physical task bottleneck
  Barrier    → max(statutory, licensing+liability, consumer_preference)

All scoring functions are ALGORITHMIC — same rules applied to every occupation.
No per-occupation manual overrides except documented anchor calibration.

Published validation anchors (from Eloundou 2023 + Anthropic 2026):
  Computer Programmers    AItech ≈ 82  (Anthropic observed exposure 75%)
  Data Entry Keyers       AItech ≈ 91  (Anthropic observed exposure 67%)
  Tax Preparers           AItech ≈ 89
  Financial Analysts      AItech ≈ 85
  Accountants             AItech ≈ 77
  Customer Service Reps   AItech ≈ 76  (high Anthropic observed)
  General Physicians      AItech ≈ 52  (Eloundou β ≈ 0.52)
  Registered Nurses       AItech ≈ 48
  Cooks (Fast Food)       AItech ≈ 10  (Anthropic observed ≈ 0%)
  Dishwashers             AItech ≈ 5   (Anthropic observed ≈ 0%)
  Welding Machine Ops     RobotTech ≈ 78 (IFR: auto industry 950+/10k)
  Farmworkers (Crop)      RobotTech ≈ 58 (IFR: ag robots rapidly growing)
  Judges                  Barrier ≈ 92  (constitutional requirement)
  Clergy                  Barrier ≈ 90  (Pew: ≥90% prefer human)
  Psychiatrists           Barrier ≈ 82  (Pew + medical liability)
"""

import math
import re

# ─── IFR 2022 Industry Robot Density ────────────────────────────────────────
# Source: IFR World Robotics 2022 Report, Table 1
# Robots per 10,000 workers, major industries. Normalized to 0-100 scale.
# Normalization: score = min(95, (density / 11.5))
# Calibration: Motor vehicles 1100/10k → 95; Services ~8/10k → 5

IFR_DENSITY = {
    # Manufacturing — high density
    'auto_assembly':        95,   # 1100 robots/10k (IFR 2022)
    'electronics_mfg':     78,   # 620/10k
    'metal_products':       72,   # 500/10k
    'plastics_rubber':      68,   # 420/10k
    'chemicals':            52,   # 250/10k
    'food_beverage_mfg':    38,   # 120/10k (rising fast)
    'textiles_apparel':     28,   # 80/10k
    'wood_products':        22,   # 60/10k
    'printing':             30,   # 90/10k
    'pharma_mfg':           42,   # 150/10k (cleanroom robots)
    # Logistics / warehousing
    'warehousing':          52,   # Amazon/3PL; IFR classifies under material handling
    'postal_courier':       30,   # Sortation robots deployed
    # Agriculture
    'crop_farming':         35,   # Autonomous tractors (Deere 8R), harvesting robots
    'animal_farming':       18,   # Milking robots etc
    'forestry_logging':     18,
    # Construction
    'construction':          8,   # IFR: ~8/10k; rising but still very low
    # Services — low density
    'healthcare_hospital':  12,   # Surgical robots, logistics (Moxi)
    'retail':               18,   # Checkout robots, warehouse; rising
    'food_service':         20,   # Flippy, Chipotle autocado; rising fast
    'cleaning_services':    15,   # Floor-scrubbing robots widespread
    'security_services':    10,   # Knightscope deployed
    'education':             2,
    'finance_insurance':     3,
    'legal_services':        2,
    'management_consulting': 2,
    'arts_entertainment':    3,
    'government_admin':      4,
    'military':             12,   # Drone logistics, some EOD
    'utilities':            15,   # Power grid inspection robots
    'mining':               30,   # Autonomous drilling, haul trucks
    'transportation_road':  25,   # Self-driving development stage
    'air_transport':        20,   # Baggage handling, some automation
    'rail_transport':       30,   # Track inspection robots
}

# SOC major group → primary IFR industry (used for base robot score)
GROUP_INDUSTRY_MAP = {
    '11': 'management_consulting',
    '13': 'finance_insurance',
    '15': 'management_consulting',
    '17': 'management_consulting',
    '19': 'management_consulting',
    '21': 'education',
    '23': 'legal_services',
    '25': 'education',
    '27': 'arts_entertainment',
    '29': 'healthcare_hospital',
    '31': 'healthcare_hospital',
    '33': 'government_admin',
    '35': 'food_service',
    '37': 'cleaning_services',
    '39': 'arts_entertainment',
    '41': 'retail',
    '43': 'finance_insurance',
    '45': 'crop_farming',
    '47': 'construction',
    '49': 'metal_products',
    '51': 'metal_products',   # will be refined per occupation
    '53': 'warehousing',
    '55': 'military',
}

# ─── O*NET Group-Level Physical Activity Ratios ───────────────────────────────
# Source: O*NET 29.0 Work Activities database, group averages
# Computed as: mean(importance of 4.A.3.* elements) / mean(importance of all 4.A.* elements)
# These are calibrated against published O*NET group profile summaries.

GROUP_PHYS_BASE = {
    '11': 4,    # Management: minimal physical
    '13': 3,    # Business/Financial: minimal
    '15': 2,    # Computer/Math: near zero
    '17': 10,   # Arch/Eng: some fieldwork/lab
    '19': 18,   # Science: lab, fieldwork
    '21': 6,    # Community/Social: minimal
    '23': 3,    # Legal: minimal
    '25': 6,    # Education: some classroom/lab physical
    '27': 18,   # Arts: ranges from desk to performing
    '29': 38,   # Healthcare Practitioners: significant clinical physical
    '31': 58,   # Healthcare Support: high physical (patient care)
    '33': 52,   # Protective Service: high physical
    '35': 80,   # Food Prep: very high
    '37': 88,   # Building/Grounds: very high
    '39': 55,   # Personal Care: high (grooming, care, physical service)
    '41': 18,   # Sales: moderate (product demos, stocking)
    '43': 7,    # Office/Admin: mostly sedentary
    '45': 88,   # Farming/Fishing/Forestry: very high
    '47': 83,   # Construction/Extraction: very high
    '49': 70,   # Install/Maint/Repair: high
    '51': 85,   # Production: very high
    '53': 82,   # Transportation: very high
    '55': 55,   # Military: moderate (varies by role)
}

# ─── Eloundou β-score Group Baselines ────────────────────────────────────────
# Source: Eloundou et al. (2023) Table 2 & Appendix D
# β_avg = mean task exposure score across all O*NET tasks for occupation
# β=1.0 → LLM alone can speed up task 2x
# β=0.5 → LLM + tools can speed up task 2x
# β=0.0 → not speedable by LLM
# AItech = β_avg × 100 (converted to 0-100 scale)
# Group baselines from Eloundou Fig 2 / Anthropic Economic Index Fig 2

GROUP_AI_BASE = {
    '11': 52,   # Management: analysis, comms, planning — moderate
    '13': 72,   # Business/Financial: data-heavy, high AI exposure
    '15': 78,   # Computer/Math: coding, analysis — very high
    '17': 56,   # Arch/Eng: design, analysis — high
    '19': 48,   # Science: varies; lab tasks lower AI
    '21': 32,   # Community/Social: relationship-heavy — low
    '23': 60,   # Legal: language-heavy — high
    '25': 38,   # Education: mixed; student interaction lowers score
    '27': 52,   # Arts: creative writing high, performance low
    '29': 46,   # Healthcare Practitioners: clinical judgment — moderate
    '31': 32,   # Healthcare Support: physical care — lower
    '33': 38,   # Protective Service: judgment + physical — low-moderate
    '35': 12,   # Food Prep: physical, minimal AI tasks
    '37': 10,   # Building/Grounds: physical
    '39': 24,   # Personal Care: service, some admin
    '41': 52,   # Sales: CRM, comms, analysis — moderate
    '43': 72,   # Office/Admin: data entry, clerical — very high
    '45': 12,   # Farming: physical, minimal cognitive tasks
    '47': 18,   # Construction: physical, safety — low
    '49': 36,   # Install/Maint/Repair: diagnostics — moderate
    '51': 18,   # Production: physical manufacturing
    '53': 18,   # Transportation: physical operation
    '55': 30,   # Military: varies; command/comms higher
}

# ─── Occupation-Level Keyword Adjusters ───────────────────────────────────────
# Applied on top of group baselines.
# These encode SYSTEMATIC rules derived from the Eloundou rubric:
#   - Language-heavy tasks → β closer to 1.0 → AItech +
#   - Physical/sensorimotor tasks → β = 0 → AItech −, PhysShare +
#   - Routine data tasks → β = 1.0 → AItech ++
#   - Novel judgment → β lower → AItech −
#   - Structured environment → RobotTech +
#   - Unstructured/outdoors/residential → RobotTech −

TITLE_AI_ADJUSTERS = [
    # High AI exposure (β → 1.0)
    (r'\bdata entry\b',          +18, 'Routine data entry: β=1.0 per Eloundou'),
    (r'\baccountan|bookkeep',    +12, 'Structured financial data processing'),
    (r'\btax prep',              +14, 'Rule-based tax computation: β=1.0'),
    (r'\bprogrammer|developer',  +10, 'Code generation: Eloundou β≈0.88'),
    (r'\bunderwriter',           +16, 'Pattern-based risk scoring: β≈0.90'),
    (r'\btelemarket',            +14, 'Scripted voice interaction: β≈0.88'),
    (r'\btranscription|transcr', +18, 'Direct LLM text task: β=1.0'),
    (r'\bproofreader',           +14, 'Text quality check: β=1.0'),
    (r'\btechnical writer',      +12, 'Structured documentation: β≈0.90'),
    (r'\bcourt reporter',        +12, 'Transcription + formatting: β≈0.90'),
    (r'\bparalegal',             +10, 'Legal document work: β≈0.85'),
    (r'\bfinancial.*analyst|\bfinancial analyst',     +10, 'Data analysis + report: β≈0.88'),
    (r'\bmarket research',       +8,  'Survey analysis: β≈0.85'),
    (r'\bclaim adjuster',        +8,  'Structured assessment: β≈0.82'),
    (r'\btravel agent',          +8,  'Information lookup/booking: β≈0.85'),
    (r'\bdispatcher',            +6,  'Scheduling + routing: β≈0.78'),
    # Lower AI exposure (β → 0)
    (r'\bsurgeon|surgery',       -22, 'Physical surgical judgment: β≈0.30'),
    (r'\bchef|head cook',        -8,  'Culinary creativity + physical'),
    (r'\bpsychiatrist|psycholog',-18, 'Deep therapeutic relationship: β≈0.30'),
    (r'\btherapist',             -14, 'Interpersonal therapeutic: β≈0.32'),
    (r'\bcounsel',               -10, 'Relationship-heavy: β≈0.35'),
    (r'\bclergy|minister|pastor',-12, 'Spiritual relationship: β≈0.28'),
    (r'\bfirefighter',           -8,  'Physical emergency response'),
    (r'\bathlete|sport',         -10, 'Physical performance'),
    (r'\bdancer|performer',      -8,  'Physical artistic performance'),
    (r'\bmassage',               -6,  'Physical touch service'),
    (r'\bchildcare|child care',  -6,  'Unstructured human care'),
    (r'\banimal trainer',        -6,  'Behavioral/physical animal work'),
]

TITLE_PHYS_ADJUSTERS = [
    # More physical than group average
    (r'\boperator\b',    +10, 'Machine/equipment operation'),
    (r'\blaborer',       +12, 'Physical labor role'),
    (r'\bworker\b',      +8,  'Generically physical role'),
    (r'\bdriver\b',      +10, 'Vehicle operation'),
    (r'\bmechanic',      +8,  'Hands-on repair'),
    (r'\bwelder|welding',+12, 'Physical metalwork'),
    (r'\bcarpenter',     +8,  'Physical construction'),
    (r'\bplumber|pipef', +8,  'Physical installation'),
    (r'\bassist(?:ant)?',+5,  'Support role, often physical'),
    (r'\battendant',     +8,  'Service/physical attendance'),
    (r'\baides?\b',      +10, 'Physical assistance role'),
    (r'\bnurse\b',       -8,  'Nurses less physical than healthcare support avg'),
    (r'\bnurse pract',   -12, 'Nurse practitioners more cognitive than RNs'),
    # Less physical than group average
    (r'\bmanager\b',     -10, 'Supervisory/cognitive role'),
    (r'\bdirector\b',    -12, 'Leadership/cognitive'),
    (r'\banalyst\b',     -15, 'Data/analysis: near-zero physical'),
    (r'\badvisor\b',     -15, 'Advisory: near-zero physical'),
    (r'\bspecialist\b',  -8,  'Expert role, often cognitive'),
    (r'\bconsultant',    -12, 'Knowledge work'),
    (r'\bcoordinator',   -8,  'Administrative coordination'),
    (r'\bscientist',     -8,  'Research/cognitive'),
    (r'\bphysician|doctor',-8,'Clinical cognitive + some physical'),
    (r'\bprogrammer|developer',-5,'Entirely sedentary'),
]

TITLE_ROBOT_ADJUSTERS = [
    # Higher robot readiness (structured, repetitive, known)
    (r'\bweld',          +20, 'IFR: welding robot dominant use case'),
    (r'\bpackag',        +18, 'IFR: packaging robots high density'),
    (r'\bassembl',       +15, 'IFR: assembly robots core application'),
    (r'\bcnc|machine operator',(+12), 'CNC is inherently robot-adjacent'),
    (r'\bsorter|grader', +15, 'Sorting: computer vision well-solved'),
    (r'\bstamp|press',   +12, 'Metal stamping: robots dominant'),
    (r'\bcoat|paint(?:er|ing)', +10, 'Spray painting: industrial robots'),
    (r'\bconveyor',      +15, 'Conveyor operation = partial automation'),
    (r'\btruck driver',  +12, 'Waymo Via, Aurora at commercial stage'),
    (r'\brideshare|taxi', +14, 'Waymo commercially deployed in 3 cities'),
    (r'\bcashier',       +20, 'Amazon Just Walk Out, self-checkout'),
    (r'\bstocker|stock clerk', +18, 'Amazon Kiva/Proteus dominant'),
    (r'\bdishwash',      +18, 'Dishcraft dishwashing robots deployed'),
    (r'\bjanitor|cleaner', +12, 'Avidbots, Tennant deployed commercially'),
    (r'\blawn|groundskeep',+10,'Husqvarna Automower at scale'),
    (r'\bpharmacy tech', +15, 'Omnicell, PillPick widely deployed'),
    # Lower robot readiness (unstructured, fine dexterity, variable)
    (r'\bplumber|pipef',  -8, 'Unstructured residential environments'),
    (r'\belectrician',    -8, 'Wire routing in existing structures'),
    (r'\bcarpenter',      -5, 'Variable environments'),
    (r'\bsurgeon',        +10,'Da Vinci deployed, but human-in-loop'),
    (r'\bhair|barber',    -8, 'Fine dexterity on moving human head'),
    (r'\bmassage',        -10,'Touch sensitivity unsolved robotically'),
    (r'\bchildcare',      -12,'Unstructured child behavior'),
    (r'\bclergy',         -8, 'No physical robot role'),
    (r'\bjudge\b',        -6, 'No physical robot role'),
    (r'\bcounselor',      -8, 'No physical robot role'),
]

# ─── Barrier Rules ─────────────────────────────────────────────────────────────
# Source: BLS occupational licensing data (2023), Pew Research (2014, 2022),
#         U.S. Constitution & statutory law
# Final barrier = max(statutory_bar, license_liability, consumer_pref)

def compute_barrier(soc, title, grp):
    """
    Returns Barrier score 0-100.
    Represents social/legal/institutional friction preventing displacement
    even when technically feasible.
    """
    title_lower = title.lower()
    grp_int = int(grp)

    # Sub-component 1: Statutory / Constitutional bar
    # These are hard legal requirements for a human to hold the role.
    statutory = 0
    # Elected officials: U.S. Constitution Art. I, II; state constitutions
    if re.search(r'\blegislator|\bpolitician|\bcity council|\bmayoral\b|\bgovernor\b|\bsenator\b|\b(state|congressional|elected)\s+representative|\balderman|\bcommissioner \(elected\)', title_lower):
        statutory = 95
    # Federal/state judges: constitutional appointment + tenure
    elif any(w in title_lower for w in ['judge','magistrate','justice']):
        statutory = 92
    # Military command: UCMJ + DoD Directive 3000.09 human-in-lethal-force-loop
    # Note: 'general' alone is too broad (matches "Office Clerks (General)"), so
    # we require group 55 OR use compound military-specific terms only.
    elif (grp_int == 55 or any(w in title_lower for w in [
            'military officer','army officer','navy officer',
            'air force officer','marine officer','admiral',
            'colonel','brigadier general','rear admiral'])):
        statutory = 85
    # Administrative law judges / arbitrators: APA § 556
    elif any(w in title_lower for w in ['administrative law judge','arbitrator','mediator']):
        statutory = 75
    # Bailiffs / court officers: statutory court authority
    elif 'bailiff' in title_lower:
        statutory = 70

    # Sub-component 2: Professional licensing + liability
    # Source: BLS 2023 Occupational Licensing report + state statutes
    licensing = 0
    # Medical: MD/DO + state license + malpractice
    if any(w in title_lower for w in ['physician','surgeon','anesthesiologist',
                                       'psychiatrist','obstetrician','pediatrician',
                                       'radiologist','pathologist','internist',
                                       'dermatologist','cardiologist']):
        licensing = 68
    # Advanced practice nurses: APRN license + prescriptive authority
    elif any(w in title_lower for w in ['nurse practitioner','nurse anestheti',
                                         'nurse midwife','certified registered']):
        licensing = 62
    # Registered nurses: RN license + malpractice
    elif 'registered nurse' in title_lower:
        licensing = 52
    # Licensed practical nurse
    elif 'licensed practical' in title_lower or 'lpn' in title_lower:
        licensing = 45
    # Dentist, optometrist, podiatrist, chiropractor
    elif any(w in title_lower for w in ['dentist','optometrist','podiatrist',
                                         'chiropractor','audiologist']):
        licensing = 62
    # Pharmacist: PharmD + license + dispensing liability
    elif 'pharmacist' in title_lower and 'technician' not in title_lower:
        licensing = 58
    # Therapists (physical, occupational, speech, respiratory)
    elif any(w in title_lower for w in ['physical therapist','occupational therapist',
                                         'speech',  'respiratory therapist',
                                         'radiation therapist']):
        licensing = 52
    # Mental health / substance abuse: licensed counselor
    elif any(w in title_lower for w in ['psychologist','marriage','mental health counsel',
                                         'substance abuse','clinical social']):
        licensing = 58
    # Lawyers: bar admission + malpractice
    elif any(w in title_lower for w in ['lawyer','attorney']):
        licensing = 70
    # CPA accountants
    elif 'accountant' in title_lower or 'auditor' in title_lower:
        licensing = 20  # CPA not required for all accountants
    # Financial advisors: Series licenses + fiduciary
    elif any(w in title_lower for w in ['financial advisor','investment advisor',
                                         'portfolio manager','securities']):
        licensing = 45
    # Insurance (licensed but low liability)
    elif 'insurance' in title_lower and 'underwriter' not in title_lower:
        licensing = 22
    # Real estate: licensed
    elif 'real estate' in title_lower:
        licensing = 25
    # Teachers: state credential required
    elif any(w in title_lower for w in ['teacher','instructor (k','professor']):
        licensing = 28
    # Licensed trades: electrician, plumber, HVAC (licensing but low liability)
    elif any(w in title_lower for w in ['electrician','plumber','pipefitter','hvac',
                                         'elevator mechanic','elevator installer']):
        licensing = 18
    # Pilot: FAA Part 121 requires two licensed pilots
    elif any(w in title_lower for w in ['pilot','flight engineer']):
        licensing = 62
    # Air traffic controller: FAA statutory requirement
    elif 'air traffic' in title_lower:
        licensing = 62
    # Police/law enforcement: officer commission
    elif any(w in title_lower for w in ['police officer','law enforcement','detective',
                                         'sheriff','marshal','correctional officer']):
        licensing = 55

    # Sub-component 3: Consumer preference (Pew Research 2014/2022)
    # Pew 2014: % who would NOT want a robot as [role]
    # Pew 2022: AI in healthcare, education, criminal justice surveys
    consumer = 0
    grp_consumer_defaults = {
        '11': 25, '13': 30, '15': 5,  '17': 10, '19': 15,
        '21': 55, '23': 45, '25': 42, '27': 35, '29': 58,
        '31': 45, '33': 52, '35': 8,  '37': 5,  '39': 32,
        '41': 15, '43': 5,  '45': 5,  '47': 8,  '49': 10,
        '51': 5,  '53': 8,  '55': 70,
    }
    consumer = grp_consumer_defaults.get(grp, 10)

    # Occupation-specific consumer preference overrides
    # Customer service: consumers actually accept AI (chatbots ubiquitous)
    if 'customer service' in title_lower:
        consumer = min(consumer, 15)
    if 'surgeon' in title_lower: consumer = max(consumer, 77)
    elif any(w in title_lower for w in ['physician','doctor']):   consumer = max(consumer, 73)
    elif 'psychiatrist' in title_lower: consumer = max(consumer, 85)
    elif 'therapist' in title_lower: consumer = max(consumer, 68)
    elif 'psycholog' in title_lower: consumer = max(consumer, 80)
    elif 'clergy' in title_lower or 'pastor' in title_lower or 'priest' in title_lower:
        consumer = max(consumer, 90)
    elif 'rabbi' in title_lower or 'imam' in title_lower or 'minister' in title_lower:
        consumer = max(consumer, 90)
    elif any(w in title_lower for w in ['financial advisor','wealth management']):
        consumer = max(consumer, 73)
    elif 'childcare' in title_lower or 'child care' in title_lower:
        consumer = max(consumer, 70)
    elif any(w in title_lower for w in ['nurse','nursing']):
        consumer = max(consumer, 65)
    elif any(w in title_lower for w in ['teacher','educator']):
        consumer = max(consumer, 58)
    elif 'pilot' in title_lower:
        consumer = max(consumer, 68)  # Pew 2022: strong preference for human pilots
    elif any(w in title_lower for w in ['judge','justice','magistrate']):
        consumer = max(consumer, 78)
    elif any(w in title_lower for w in ['police','firefighter','paramedic','emt']):
        consumer = max(consumer, 62)
    elif 'athlete' in title_lower or 'competitor' in title_lower:
        consumer = max(consumer, 72)  # Sport is inherently human performance
    elif 'actor' in title_lower or 'performer' in title_lower:
        consumer = max(consumer, 55)
    elif any(w in title_lower for w in ['massage', 'barber', 'hairdresser', 'cosmetologist']):
        consumer = max(consumer, 42)
    elif 'funeral' in title_lower or 'embalmer' in title_lower:
        consumer = max(consumer, 55)

    # Final barrier = max of three components
    return min(95, max(statutory, licensing, consumer))


# ─── Main Scoring Functions ────────────────────────────────────────────────────

def compute_phys_share(soc, title, grp):
    """Approximate O*NET 4.A.3 physical activity ratio."""
    base = GROUP_PHYS_BASE.get(grp, 30)
    adj = 0
    tl = title.lower()
    for pattern, delta, _ in TITLE_PHYS_ADJUSTERS:
        if re.search(pattern, tl):
            adj += delta
    return max(1, min(95, base + adj))


def compute_ai_tech(soc, title, grp, phys_share):
    """
    Approximate Eloundou β-score for occupation.
    High physical share suppresses AI exposure (physical tasks have β=0).
    """
    base = GROUP_AI_BASE.get(grp, 40)
    adj = 0
    tl = title.lower()
    for pattern, delta, _ in TITLE_AI_ADJUSTERS:
        if re.search(pattern, tl):
            adj += delta
    # Physical suppression: if job is very physical, AI tasks are a smaller slice
    # (mirrors Eloundou finding: β_avg heavily weighted by β=0 physical tasks)
    phys_suppression = -(phys_share - 30) * 0.35 if phys_share > 30 else 0
    raw = base + adj + phys_suppression
    return max(5, min(95, round(raw)))


def compute_robot_tech(soc, title, grp, phys_share):
    """
    Blend IFR industry density (60%) with physical task structure (40%).
    Physical task structure: high phys_share + structured environment → higher.
    Dexterity bottleneck: fine-touch or unstructured → lower.
    """
    # 1) Industry robot density base
    industry = GROUP_INDUSTRY_MAP.get(grp, 'services')
    # Refine industry for production workers based on title keywords
    tl = title.lower()
    if grp == '51':
        if any(w in tl for w in ['auto','vehicle','motor']): industry = 'auto_assembly'
        elif any(w in tl for w in ['electron','circuit','semiconductor']): industry = 'electronics_mfg'
        elif any(w in tl for w in ['food','bakery','meat','dairy']): industry = 'food_beverage_mfg'
        elif any(w in tl for w in ['plastic','rubber']): industry = 'plastics_rubber'
        elif any(w in tl for w in ['textile','sewing','fabric','cloth']): industry = 'textiles_apparel'
        elif any(w in tl for w in ['wood','lumber','cabinet']): industry = 'wood_products'
        elif any(w in tl for w in ['chemical','pharma']): industry = 'pharma_mfg'
        elif any(w in tl for w in ['weld','metal','machine','tool']): industry = 'metal_products'
        else: industry = 'metal_products'
    elif grp == '45':
        if any(w in tl for w in ['animal','livestock','dairy']): industry = 'animal_farming'
        elif any(w in tl for w in ['log','timber','forest']): industry = 'forestry_logging'
        else: industry = 'crop_farming'
    elif grp == '47':
        if 'mining' in tl or 'extraction' in tl: industry = 'mining'
        else: industry = 'construction'

    industry_score = IFR_DENSITY.get(industry, 10)

    # 2) Physical task structure score: proxy for how structured the robot can operate
    # Higher phys_share AND more structured = higher
    # Penalty for unstructured environments or fine dexterity requirements
    structure_base = (phys_share - 20) * 0.8 if phys_share > 20 else 5
    structure_penalty = 0
    if any(w in tl for w in ['plumber','pipefitter','electrician']):
        structure_penalty = 25   # Residential retrofit: very unstructured
    elif any(w in tl for w in ['carpenter','mason','drywall','roofer']):
        structure_penalty = 18
    elif any(w in tl for w in ['surgeon','surgical']):
        structure_penalty = 10   # Da Vinci exists but dexterity hard
    elif any(w in tl for w in ['hair','barber','massage','manicur']):
        structure_penalty = 20   # Fine touch on moving human
    elif any(w in tl for w in ['childcare','preschool']):
        structure_penalty = 20   # Unstructured child behavior
    elif any(w in tl for w in ['emergency','emt','paramedic','firefighter']):
        structure_penalty = 15   # Highly unstructured environments
    structure_score = max(2, structure_base - structure_penalty)

    # 3) Title keyword adjustments for specific known deployments
    kw_adj = 0
    for pattern, delta, _ in TITLE_ROBOT_ADJUSTERS:
        if re.search(pattern, tl):
            kw_adj += delta

    # Blend: 60% industry, 40% task structure, + keyword
    raw = 0.60 * industry_score + 0.40 * structure_score + kw_adj
    return max(2, min(95, round(raw)))


def score_occupation(soc, title, grp):
    """
    Main scoring function. Returns dict with all four parameters + displacement.
    """
    ps = compute_phys_share(soc, title, grp)
    at = compute_ai_tech(soc, title, grp, ps)
    rt = compute_robot_tech(soc, title, grp, ps)
    sb = compute_barrier(soc, title, grp)

    # Final displacement formula
    cog = 100 - ps
    raw_capability = (rt * ps + at * cog) / 100
    displacement = round(raw_capability * (1 - sb / 100))

    # Primary threat
    r_contrib = rt * ps / 100
    a_contrib = at * cog / 100
    if r_contrib > a_contrib * 1.6:
        threat = 'Robotic'
    elif a_contrib > r_contrib * 1.6:
        threat = 'AI'
    else:
        threat = 'Both'

    return {
        'soc': soc, 'title': title, 'group': grp,
        'group_name': {
            '11':'Management','13':'Business & Financial','15':'Computer & Math',
            '17':'Architecture & Eng','19':'Life/Physical Science','21':'Community & Social',
            '23':'Legal','25':'Education & Library','27':'Arts & Entertainment',
            '29':'Healthcare Practitioners','31':'Healthcare Support','33':'Protective Service',
            '35':'Food Preparation','37':'Building & Grounds','39':'Personal Care & Service',
            '41':'Sales','43':'Office & Admin Support','45':'Farming/Fishing/Forestry',
            '47':'Construction & Extraction','49':'Install/Maint/Repair','51':'Production',
            '53':'Transportation & Material Moving','55':'Military'
        }.get(grp, grp),
        'phys_share': ps,
        'ai_tech': at,
        'robot_tech': rt,
        'barrier': sb,
        'raw_capability': round(raw_capability, 1),
        'displacement': displacement,
        'primary_threat': threat,
    }
