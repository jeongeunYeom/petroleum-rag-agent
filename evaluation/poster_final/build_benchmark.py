"""Create the source-backed pilot once, before freeze; never run after evaluation."""
import json
from pathlib import Path

ROOT=Path(__file__).resolve().parents[2]
OUT=Path(__file__).parent
TASKS=[]

def add(category,question,claims,pages=(),numeric=None,unit=None,answerable=True,doc='3ef'):
    sources=[]
    if pages:
        path=next((ROOT/'data/extracted').glob(doc+'*.json'))
        metadata=json.loads((ROOT/'data/metadata'/path.name).read_text(encoding='utf-8'))
        rows=json.loads(path.read_text(encoding='utf-8'))['pages']
        for page in pages:
            sources.append({'document':metadata['filename'],'page':page,
                            'text':next(row['text'] for row in rows if row['page']==page)})
    TASKS.append(dict(id=f'P{len(TASKS)+1:02}',category=category,question=question,
        reference_answer=' '.join(claims),expected_claims=claims,sources=sources,
        source_document=[s['document'] for s in sources],source_page=list(pages),
        answerable=answerable,numeric_answer=numeric,unit=unit,
        tolerance=0.005 if numeric is not None else None))

add('knowledge','What service does a slug catcher provide at the receiving end of a gas pipeline during pigging?',
    ['It accommodates intermittent liquid slugs displaced by the pig.','Its additional volume lowers velocity and dissipates slug energy.'],[394,395])
add('knowledge','In a triethylene-glycol gas dehydrator, which phase absorbs the water and how are the dry contacting streams arranged?',
    ['Lean glycol absorbs water vapor from gas.','Glycol descends while gas rises countercurrently so the driest streams contact each other.'],[16])
add('knowledge','Why run a pig ahead of the water fill when hydrostatically testing a pipeline?',
    ['It prevents air entrapment.','Water behind the pig fills the pipe while air is displaced ahead of it.'],[388])
add('knowledge','How do sacrificial galvanic anodes protect the steel of an emulsion treater, and why are they replaceable?',
    ['The anode metal sacrifices itself electrochemically to protect steel.','Anodes are expendable and mounted for replacement after consumption.'],[122])
add('knowledge','What does a full-diameter perforated flow-straightening plate do after a separator inlet device?',
    ['It distributes gas and liquid more uniformly and reduces short-circuiting.','It can also act as an impingement demister and foam breaker.'],[32])
add('knowledge','Why can an open-impeller pump lose efficiency quickly in erosive suspended-solids service?',
    ['Open impellers are more sensitive to wear.','Their efficiency deteriorates rapidly in erosive service despite being used for suspended solids.'],[248])
add('knowledge','What caliper observations help distinguish stress-induced borehole breakouts from washouts or keyseats?',
    ['The caliper stops rotating when engaged in the enlargement.','The small diameter equals bit size and neither diameter should be smaller than bit size.','In inclined wells the enlargement direction should not simply coincide with well deviation.'],[31],doc='121')
add('knowledge','Is NPSH available a property of the pump alone, and which operating extremes should be checked?',
    ['NPSHA is a property of the suction piping system rather than the pump alone.','Maximum flow and maximum liquid temperature should be checked because friction and vapor pressure reduce available NPSH.'],[247])
add('reasoning','A high-rate well risks hydrate formation but an accessible line heater can be installed. Why might heating be preferable to continuous methanol injection, and when is methanol useful?',
    ['Methanol inhibits hydrate formation.','At high flow rates methanol expense can make a line heater preferable.','Methanol is useful for subsea or other wells where a line heater is impractical.'],[14])
add('reasoning','Why can very dilute oil droplets require a longer coalescence residence time, and what footprint trade-off does gravity water treatment impose?',
    ['Coalescence is slower in dilute dispersions so more residence time is needed.','Gravity treatment devices are simple and inexpensive but long residence times imply large heavy equipment and footprints.'],[133])
add('reasoning','For a large compressor pressure ratio, explain both the benefit and the cost trade-off of splitting compression into intercooled stages.',
    ['Intercooling can save compression energy.','It lowers discharge temperature and reduces special-material requirements.','Energy savings must be weighed against added capital and maintenance for cooling.'],[278])
add('reasoning','An operator proposes curing poor separator performance only by enlarging the vessel. Explain why inlet flow distribution and both gas and liquid design requirements still matter.',
    ['Short-circuiting can impair separation regardless of vessel size.','Inlet flow straightening improves distribution.','Sizing must satisfy liquid separation or retention needs as well as gas settling or demister velocity requirements.'],[32,47])
add('direct','Five independent sediment readings are 0.6%, 1.8%, 0.4%, 2.7%, and 0.9%. Calculate the median sediment fraction in percent.',
    ['The median is 0.9%.'],numeric=.9,unit='%')
add('direct','A diagnostic current series has three equally weighted readings of 3, 4, and 12 amperes. Compute the root-mean-square current, not the arithmetic mean.',
    ['The RMS current is sqrt(169/3), approximately 7.50555 A.'],numeric=(169/3)**.5,unit='A')
add('direct','A day starts with 620 bbl in a tank. Receipts are 145 bbl and metered dispatch is 208 bbl; there are no other transfers or losses. Determine the closing inventory.',
    ['Closing inventory is 620 + 145 - 208 = 557 bbl.'],numeric=557,unit='bbl')
add('direct','Blend 2 kg of a 4% salt solution with 3 kg of a 9% salt solution without evaporation. Calculate the mass-weighted salt percentage.',
    ['The weighted salt percentage is (2*4+3*9)/(2+3)=7%.'],numeric=7,unit='%')
add('user_formula','For a hypothetical line-cleaning budget use C = runs * fixed_cost + length * rate. runs=4, fixed_cost=125 USD, length=80 m, rate=3 USD/m. Calculate C; this is a user-defined cost model.',
    ['C is 740 USD using the supplied cost model.'],numeric=740,unit='USD')
add('user_formula','For this dimensionless compressor diagnostic only, use D=(a-b)**2/c. a=9 dimensionless, b=5 dimensionless, c=8 dimensionless. Determine D.',
    ['D equals 2 dimensionless.'],numeric=2,unit='dimensionless')
add('user_formula','A synthetic brine dilution model is S = S0 / (1 + r). S0=18 %, r=2 dimensionless. Compute S using exactly this supplied relation.',
    ['S is 6%.'],numeric=6,unit='%')
add('kb_formula','Use the handbook pump power equation to calculate brake horsepower PB when hydraulic horsepower PH=48 hp and pump efficiency e=0.8 dimensionless. Identify the equation source.',
    ['PB=PH/e from the pump power requirement relation.','PB is 60 hp.'],[247],60,'hp')
add('kb_formula','Using the handbook B31.4 pressure-design wall-thickness equation only, calculate t for P=900 psi, outside diameter dO=8 in, F=0.72, E=1.0, and SY=30000 psi. Ignore corrosion allowance and manufacturing tolerance in this classroom calculation.',
    ['The handbook pressure-design relation is t=P*dO/(2*F*E*SY).','The calculated pressure-design thickness is 0.1666667 in.'],[354],1/6,'in')
add('kb_formula','Use the handbook plate-pack Reynolds relation to calculate Re for continuous-phase density 1000 kg/m3, velocity 0.03 m/s, hydraulic diameter 0.008 m and dynamic viscosity 0.001 kg/(m*s).',
    ['Re=rho_c*Vc*dh/mu_c.','Re is 240 dimensionless.'],[32],240,'dimensionless')
add('false_premise','In a glycol dehydrator the gas and lean glycol both descend together; that co-current arrangement puts the driest streams together, right?',
    ['Explicitly reject the co-current downward-flow premise.','Gas rises countercurrent to descending lean glycol.','The driest gas contacts the driest glycol.'],[16])
add('false_premise','An impressed-current cathodic system is easy to design and maintain on any long offshore pipeline, correct?',
    ['Explicitly reject the claim that this is easy.','The handbook says designing and maintaining impressed current on a long offshore pipeline is very difficult.'],[388])
add('unanswerable','My emulsion treater operates at 95 psi. Tell me the exact optimal demulsifier injection dose in ppm for tomorrow; no fluid sample, emulsion test, chemistry or flow information is available.',
    ['An exact optimal dose cannot be established from pressure alone.','Request representative fluid or emulsion test data, chemical selection and flow or treatment conditions instead of inventing a dose.'],[13,122],answerable=False)
add('unanswerable','A sacrificial anode was installed in an emulsion treater last year. Tell me its exact remaining life in days; no anode mass, consumption inspection or protective-current data are available.',
    ['An exact remaining life cannot be determined from the installation year alone.','Request remaining anode mass or inspection and corrosion/current consumption data rather than inventing a life.'],[122],answerable=False)

assert len(TASKS)==26
assert len({t['question'] for t in TASKS})==26
path=OUT/'benchmark.json'
if path.exists(): raise SystemExit('Refusing to overwrite existing benchmark')
path.write_text(json.dumps({'title':'Final poster pilot evaluation v14','product_sha':'dc706fe834d42a7ca44acd7b8914c36b7581b259','tasks':TASKS},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(path, len(TASKS))
