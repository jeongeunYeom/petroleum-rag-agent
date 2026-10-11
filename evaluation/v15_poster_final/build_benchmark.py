"""Authoring receipt: new candidates from read-only KB, before old-task screening.

Never run after freeze. This is evaluation data construction, not product code.
"""
import hashlib
import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parent
DB = Path('D:/petroleum-rag-agent/data/vector_db/chroma.sqlite3')
assert not (ROOT / 'freeze_receipt.json').exists(), 'Frozen; authoring disabled'
db = sqlite3.connect(DB.as_uri() + '?mode=ro', uri=True)

def source(row):
    values = dict(db.execute('select key, coalesce(string_value,int_value) from embedding_metadata where id=?', (row,)))
    chunk = db.execute('select embedding_id from embeddings where id=?', (row,)).fetchone()[0]
    return {'chunk_id': chunk, 'source_document': values['document'], 'source_page': values['page'], 'supporting_span': values['chroma:document']}

tasks = []
def add(category, question, claims, rows=(), numeric=None, formula=None, variables=None):
    tasks.append(dict(id=f'P{len(tasks)+1:02}', category=category, question=question,
        answerable=category != 'unanswerable', required_claims=claims,
        sources=[source(i) for i in rows], numeric_targets=numeric or [],
        source_formula=formula, required_variables=variables or {}))

def num(label, value, unit, tolerance=0.01):
    return dict(label=label, value=value, unit=unit, absolute_tolerance=tolerance,
                equivalent_units_allowed=True)

add('knowledge', 'In a rod-pumped oil well, what is a gas anchor intended to separate, and where does the separated gas go? Explain from the internal petroleum references.',
    ['Separates free gas from liquid before liquid enters the pump.', 'Separated gas enters the tubing/casing annulus for venting or gathering.'], [4029])
add('knowledge', 'When drilling circulation stops, which mud property keeps cuttings suspended, and how is that different from removing drilled solids at surface?',
    ['Static gel/thixotropic properties suspend cuttings when circulation stops.', 'Surface mechanical equipment such as shale shakers/desanders/desilters removes drilled solids.'], [2674])
add('knowledge', 'What distinguishes a secondary squeeze cement job from the initial cementing of a well? Give two remedial purposes supported by the internal drilling text.',
    ['Secondary squeeze cementing is remedial work later in well life, forcing cement into place/through holes.', 'It can seal water-producing zones.', 'It can repair casing leaks.'], [2567,2037])
add('knowledge', 'For a progressing cavity pump exposed to aromatic crude and dissolved gas, what elastomer problems and operating precaution does the artificial-lift text identify?',
    ['Elastomer compatibility with aromatic crude requires testing.', 'Gas dissolved under high bottomhole pressure can form destructive bubbles when pressure drops rapidly.', 'Avoid rapid depressurisation of the pump.'], [4115])
add('knowledge', 'For a centrifugal pump, explain the relationship required between available and required net positive suction head and what may happen if it is not met.',
    ['NPSHA must equal or exceed NPSHR.', 'Insufficient NPSHA can cause cavitation or flashing at pump suction.'], [17359])
add('knowledge', 'Why can an oil-based drilling mud become excessively viscous as its emulsified water fraction or fine drilled-solids content increases?',
    ['Properly emulsified water behaves like a solid, so more water raises viscosity.', 'Fine drilled solids can raise plastic viscosity, yield point and gel strength.'], [2740])

add('reasoning', 'In water-wet reservoir rocks, connect pore size, capillary pressure and retained interstitial water to explain why a silty fine sand can retain more water than a coarse sand. Use the relevant relationships, not just a definition.',
    ['Smaller pores have higher capillary pressure.', 'Water wets rock surfaces and occupies the smallest pores.', 'Fine/silty sand therefore tends toward higher retained interstitial water than coarse large-pore sand.'], [892,885])
add('reasoning', 'A drilling crew increases weight on bit but penetration does not improve while bit passages are clogged with cuttings. Explain why more weight may not help and connect hydraulic horsepower and nozzle flow to possible cleaning changes.',
    ['Bit/bottomhole balling and inadequate hydraulic horsepower can limit penetration despite added WOB.', 'Increasing nozzle pressure drop or flow increases bit hydraulic horsepower.', 'Hydraulic/nozzle changes must consider other effects such as annular velocity; extended or additional nozzles can improve cleaning.'], [2266,2267])
add('reasoning', 'An unintentionally foaming cement slurry appears light in the surface densitometer. Explain why that reading may underestimate downhole density and how severe foaming can nevertheless threaten hydrostatic pressure during pumping.',
    ['Entrained air is included in surface density measurements.', 'Air compresses under downhole pressure, so actual downhole density can be higher.', 'Severe foam can cause pump cavitation and loss of hydrostatic pressure.'], [15628])
add('reasoning', 'A reservoir model is coarsened for computational speed. Connect grid-size error with the reason for using pseudo-relative permeabilities rather than simply transferring rock relative permeabilities unchanged.',
    ['Coarse grids introduce numerical dispersion/grid-size sensitivity.', 'Pseudo-relative permeabilities control numerical dispersion and account for layering.', 'Fine-grid models use rock relative permeability whereas coarse models may require pseudo properties.'], [5223])

add('direct_calculation', 'A separator inspection log recorded shutdowns lasting 26, 43, 18 and 57 minutes. What were the total downtime and the arithmetic mean duration per shutdown?',
    ['Total downtime is 144 minutes.', 'Mean duration is 36 minutes.'], numeric=[num('total downtime',144,'min'),num('mean duration',36,'min')])
add('direct_calculation', 'Seven retained core pieces have measured lengths of 14, 29, 17, 33, 21, 26 and 19 cm. Report the median length and the difference between longest and shortest.',
    ['Median length is 21 cm.', 'Longest minus shortest is 19 cm.'], numeric=[num('median',21,'cm'),num('range',19,'cm')])
add('direct_calculation', 'During a gas-handling trial, 8640 standard cubic metres were captured and 720 standard cubic metres were flared. Express captured volume divided by flared volume as a dimensionless ratio.',
    ['Captured-to-flared ratio is 12 (12:1).'], numeric=[num('captured/flared',12,'dimensionless')])
add('direct_calculation', 'For a filter-maintenance job, cartridges cost 1280 dollars and labour costs 965 dollars, but the supplier issues a 185-dollar credit. Against a 2000-dollar budget, what is the net job cost and the percentage budget overrun after applying the credit?',
    ['Net cost after credit is 2060 dollars.', 'Budget overrun is 3 percent, using the budget as denominator.'], numeric=[num('net cost',2060,'USD'),num('budget overrun',3,'%')])

add('user_formula', 'For a hypothetical dimensionless screening index use mixIndex = (alphaBlend + 2*betaBlend)/(1 + gammaBlend). With alphaBlend = 7.2, betaBlend = 3.4 and gammaBlend = 0.6, calculate mixIndex. This supplied relation defines the model; no handbook relation is needed.',
    ['Applies the supplied relation with all three operands.', 'mixIndex is 8.75, dimensionless.'], numeric=[num('mixIndex',8.75,'dimensionless')], formula='mixIndex = (alphaBlend + 2*betaBlend)/(1 + gammaBlend)',variables={'alphaBlend':7.2,'betaBlend':3.4,'gammaBlend':0.6})
add('user_formula', 'A hypothetical dimensionless deposition indicator is depositMetric = dwellFactor*dwellFactor - 3*dwellFactor + solventOffset/2. Evaluate it at dwellFactor = 4.6 and solventOffset = 5.8 using only this supplied model.',
    ['Uses the quadratic term and both supplied operands.', 'depositMetric is 10.26, dimensionless.'], numeric=[num('depositMetric',10.26,'dimensionless')],formula='depositMetric = dwellFactor*dwellFactor - 3*dwellFactor + solventOffset/2',variables={'dwellFactor':4.6,'solventOffset':5.8})
add('user_formula', 'Use this hypothetical dimensionless mixing rule: mixRule = (blendGain*contactScale + offsetLoad)/(contactScale + 2). The coefficients are blendGain = 6.3, contactScale = 2.5 and offsetLoad = 9.45. What is mixRule? Do not substitute a physical correlation for the given rule.',
    ['Uses the supplied rational relation and all coefficients.', 'mixRule is 5.6, dimensionless.'],numeric=[num('mixRule',5.6,'dimensionless')],formula='mixRule = (blendGain*contactScale + offsetLoad)/(contactScale + 2)',variables={'blendGain':6.3,'contactScale':2.5,'offsetLoad':9.45})

add('kb_formula', 'A mud pump delivers 420 gpm at 2850 psi. Find the hydraulic-horsepower relation in the internal drilling reference and use it to determine the hydraulic output, not the shaft input power.',
    ['Uses HHP = pressure in psi times flow in gpm divided by 1714.', 'Hydraulic output is about 698.37 hp.'], [2116], [num('HHP',2850*420/1714,'hp',0.05)], 'HHP = P*Q/1714', {'P':{'value':2850,'unit':'psi'},'Q':{'value':420,'unit':'gpm'}})
add('kb_formula', 'An acoustic fluid-level echo in a casing/tubing annulus returns after 3.8 seconds. The calibrated sound speed in that annulus is 410 m/s. Find the internal artificial-lift text relationship and calculate the fluid-level depth from the acoustic travel time.',
    ['Uses round-trip travel time, so depth is half sound speed times elapsed time.', 'Fluid-level depth is 779 m.'], [4028], [num('depth',779,'m')], 'depth = time*sound_speed/2', {'time':{'value':3.8,'unit':'s'},'sound_speed':{'value':410,'unit':'m/s'}})
add('kb_formula', 'At a fixed pump rate the measured surface pump pressure is 3125 psi and the pressure loss across the bit is 1170 psi. Locate the drilling-hydraulics relationship for circulating-system pressure loss and calculate that loss.',
    ['Uses Pcirc = Psurf - Pbit.', 'Circulating-system pressure loss is 1955 psi.'], [2840], [num('Pcirc',1955,'psi')], 'Pcirc = Psurf - Pbit', {'Psurf':{'value':3125,'unit':'psi'},'Pbit':{'value':1170,'unit':'psi'}})

add('false_premise', 'In a water-bearing formation, mud-filtrate invasion leaves the water saturation unchanged, so the resistivity must remain unchanged too. Is that inference correct? Explain using the internal formation-evaluation text.',
    ['Explicitly rejects the inference that unchanged water saturation guarantees unchanged resistivity.', 'Filtrate invasion can change salinity.', 'Salinity changes can change resistivity despite unchanged water saturation.'], [81])
add('false_premise', 'An invert oil-emulsion drilling mud has oil droplets dispersed in a continuous water phase, correct? Check that statement against the drilling reference and identify the actual continuous and dispersed phases.',
    ['Explicitly rejects the reversed phase description.', 'Oil is the continuous phase.', 'Water is dispersed as droplets in the oil.'], [2016])
add('unanswerable', 'Our progressive-cavity pump will handle a new aromatic crude. What exact maximum aromatic concentration can its elastomer tolerate? We have not specified the elastomer compound, temperature or compatibility-test results. Identify what is needed rather than inventing a concentration limit.',
    ['States an exact concentration tolerance cannot be determined from the given information.', 'Requests elastomer identity/compound and operating temperature.', 'Requests relevant fluid composition and compatibility-test/manufacturer data instead of inventing a limit.'], [4115])
add('unanswerable', 'Give the exact minimum suction-vessel liquid level that will prevent cavitation for our centrifugal pump. Its model, speed, suction piping losses, liquid properties and operating pressure have not been supplied. Explain the specific data needed to determine the level.',
    ['Cannot determine an exact minimum level from the supplied information; does not invent one.', 'Needs pump NPSHR at operating duty/speed and pump datum/elevation.', 'Needs suction pressure, liquid temperature/vapour pressure/density and suction losses/flow to determine NPSHA.'], [17359])

assert len(tasks)==24 and sum(bool(t['numeric_targets']) for t in tasks)==10
payload={'name':'v15 final independent poster pilot','product_sha':'6b8b0e7850a24b79b337882b1de3184cb7993d04',
    'authorship':'New candidates authored from live read-only Chroma spans and original arithmetic models before accessing old tasks for deduplication.',
    'tasks':tasks}
out=ROOT/'benchmark.json'
out.write_text(json.dumps(payload,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(len(tasks),hashlib.sha256(out.read_bytes()).hexdigest())
