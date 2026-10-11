"""Pre-freeze authoring from current read-only Chroma spans, never historical cases."""
import json, sqlite3, hashlib
from pathlib import Path
P=Path(__file__).resolve().parent
ROOT=P.parents[1]
c=sqlite3.connect(f'file:{ROOT.as_posix()}/data/vector_db/chroma.sqlite3?mode=ro',uri=True)
metadata={}
for i,k,s,n,f,b in c.execute('select * from embedding_metadata order by id,key'):
    metadata.setdefault(i,{})[k]=next((v for v in (s,n,f,b) if v is not None),None)
tasks=[]
def add(category, question, claims, rows=(), numeric=None, unit=None, formula=None, variables=None, answerable=True):
    sources=[dict(source_document=metadata[i]['document'],source_page=metadata[i]['page'],supporting_span=metadata[i]['chroma:document'],sqlite_row=i) for i in rows]
    tasks.append(dict(id=f'V16-{len(tasks)+1:02}',question=question,category=category,answerable=answerable,required_claims=claims,sources=sources,source_document=[s['source_document'] for s in sources],source_page=[s['source_page'] for s in sources],supporting_span=[s['supporting_span'] for s in sources],numeric_gold=numeric,unit=unit,tolerance=0.01 if numeric is not None else None,formula=formula,required_variables=variables or {}))
add('knowledge','시추 가스 분석용 thermal conductivity detector(TCD)는 기체 조성 차이를 어떻게 전기 신호로 바꾸며, reference cell은 어떤 역할을 하나요?',[
'Gas composition changes thermal conductivity and therefore filament cooling and resistance at controlled flow.', 'Reference cell carries pure carrier gas; reference/sample filaments form Wheatstone bridge arms.'],[8444,8445])
add('knowledge','상대투과도 측정의 Penn-State three-plug 방법에서 중앙 플러그와 양쪽 바깥 플러그의 역할을 구분해 설명해줘.',[
'Only central plug is measured.', 'Inlet outer plug mixes fluids; outlet outer plug alleviates capillary end effects.'],[5844])
add('knowledge','완결정에서 부식 억제제를 깊은 위치에 주입하려고 할 때 casing-tubing annulus와 side pocket mandrel을 이용하는 구성을 설명해줘.',[
'Inject treatment fluid into casing-tubing annulus.', 'Side pocket mandrel valve opens under prescribed pressure conditions to introduce treatment into tubing at depth.'],[3300,3301])
add('knowledge','Oil-based drilling fluid의 electrical stability를 감시하는 목적과, 갑자기 지층수가 유입될 때 에멀전이 가져야 할 성질을 설명해줘.',[
'Electrical stability monitors strength/stability of internal brine or water emulsion.', 'Emulsion should tolerate incorporating additional water on a downhole influx.'],[14691,14692])
add('knowledge','Coiled tubing에서 동일한 bend-cycle을 수명 후반에 받는 경우와 초기에 받는 경우를 같은 손상으로 합산해도 될까요? 교재의 피로 수명 설명을 근거로 답해줘.',[
'No, fatigue damage cannot generally be applied linearly to life prediction.', 'Equivalent bend loading later in life may cause greater fatigue damage than early loading.'],[16490])
add('knowledge','Flash liberation과 differential liberation은 발생한 가스가 액체와 계속 접촉하는지에서 어떻게 다르며, 왜 Rs 측정 결과가 달라질 수 있나요?',[
'Flash keeps evolved gas in contact until equilibrium.', 'Differential removes evolved gas from liquid, changing the remaining system and yielding different Rs.'],[739])
add('reasoning','시추유체에서 고염도 수상은 shale 억제에 도움이 된다는데, bentonite를 염수에 직접 섞어 점도를 만드는 일은 왜 어려울 수 있나요? Attapulgite 대안을 쓸 때의 장점과 한계도 연결해 설명해줘.',[
'High-salinity water inhibits shale hydration/swelling.', 'Calcium and magnesium reduce clay hydration/dispersion, impairing bentonite yield.', 'Attapulgite does not rely on makeup-water type to build viscosity but costs more and gives poor filtration control.'],[14692,2710])
add('reasoning','물에 젖은 가스의 choke 감압을 거의 단열·무축일 과정으로 볼 때 enthalpy와 온도에 대해 무엇을 구분해야 하나요? 냉각 전 glycol 주입이 왜 필요한지도 연결해줘.',[
'No shaft work and nearly adiabatic restriction implies constant enthalpy, not constant temperature.', 'Joule-Thomson cooling can enter hydrate conditions; glycol before cooling prevents water forming ice/hydrates.'],[13441,13443,4813])
add('reasoning','모래가 separator 내부에 쌓이고, 동시에 잘 분리되지 않는 유수 에멀전이 들어오는 상황입니다. 모래 축적의 체류시간 영향과 에멀전 처리상 불리한 이유, 가능한 처리 방안을 연결해 설명해줘.',[
'Sand accumulation reduces separator residence time.', 'Emulsion may need more time than available; reduced residence impairs separation.', 'Heating to reduce viscosity or demulsifying chemicals are possible remedies, not guaranteed universal cures.'],[4665,4796])
add('reasoning','가스 함유층에서 compressional sonic porosity만으로 해석할 때의 주의점과 shear 정보를 함께 쓰는 이점을 설명해줘. P파와 S파의 pore-fluid 민감도 차이를 연결하고, 셰일 보정 필요 여부도 밝혀줘.',[
'P waves respond to rock matrix and pore fluid; S waves weakly or not sensitive to pore fluid changes.', 'Shear-based porosity is insensitive to gas effects and can complement compressional data.', 'Basic clean water-filled models require corrections for shale/hydrocarbons as applicable.'],[7513,7964])
add('direct_calculation','다섯 번의 시추 연결 작업 소요시간은 6.4, 7.1, 5.8, 8.3, 6.9 min입니다. 합계와 산술평균을 각각 계산해줘. 추가 자료 검색은 필요 없습니다.', ['Total 34.5 min.', 'Mean 6.9 min.'],numeric={'total':34.5,'mean':6.9},unit='min')
add('direct_calculation','Separator 배출수의 탁도 측정치는 42, 19, 37, 26, 51 NTU입니다. 중앙값과 최댓값-최솟값 범위를 구해줘.', ['Median 37 NTU.', 'Range 32 NTU.'],numeric={'median':37,'range':32},unit='NTU')
add('direct_calculation','펌프 정지시간이 정비 전 46 h에서 정비 후 29 h가 됐습니다. 감소량과 정비 전 대비 감소율을 계산하고 반올림해 소수 둘째 자리까지 보여줘.', ['Decrease 17 h.', 'Percentage decrease 36.96 percent.'],numeric={'difference':17,'percentage_decrease':36.956521739},unit={'difference':'h','percentage_decrease':'%'})
add('direct_calculation','분리 실험에서 회수한 오일 질량은 73 kg, 투입 오일 질량은 91 kg입니다. 회수/투입 비율과 회수되지 않은 오일 질량을 계산해줘.', ['Recovery ratio 0.8021978 or 80.21978%.', 'Unrecovered mass 18 kg.'],numeric={'ratio':73/91,'unrecovered_mass':18},unit={'ratio':'dimensionless','unrecovered_mass':'kg'})
add('user_formula','가상의 separator 부하 지수는 L = 0.8*q**2 + 1.3*q + 2.1 이다. q=3.5는 무차원이고 L도 무차원이다. 이 관계식만 사용해 L을 계산해줘.', ['L=16.45 dimensionless.'],numeric={'L':16.45},unit='dimensionless',formula='L=0.8*q**2+1.3*q+2.1',variables={'q':3.5})
add('user_formula','약품 구매비의 가상 모델 C = a*m + b를 사용해줘. a=4.7 USD/kg, m=38 kg, b=26 USD일 때 총 비용 C를 구해줘. 다른 상관식은 필요 없어.', ['C=204.6 USD.'],numeric={'C':204.6},unit='USD',formula='C=a*m+b',variables={'a':4.7,'m':38,'b':26})
add('user_formula','가상 필터 압력손실 모델 dP = k*v**2를 적용한다. k=1.75 kPa/(m/s)^2, v=2.8 m/s일 때 dP를 계산해줘.', ['dP=13.72 kPa.'],numeric={'dP':13.72},unit='kPa',formula='dP=k*v**2',variables={'k':1.75,'v':2.8})
add('kb_formula','Two-phase piping의 API RP14E erosional velocity 식을 내부 handbook에서 찾아 적용해줘. 혼합물 flowing density는 49 lb/ft^3, 이 단위계의 empirical C는 112이다. 상관식이 주는 속도를 ft/s로 계산하되 실제 안전 운전속도 보증으로 해석하지 마.', ['Use Ve=C/sqrt(rhoM).', 'Correlation velocity 16 ft/s; not a guarantee of safe operating velocity.'],[17654],numeric={'Ve':16},unit='ft/s',formula='Ve=C/sqrt(rhoM)',variables={'C':'112 in field-unit convention','rhoM':'49 lb/ft^3'})
add('kb_formula','이상기체로 보는 가스 혼합물의 apparent molecular weight가 23.49 g/mol입니다. 공기의 molecular weight를 29.0 g/mol로 두고 내부 교재의 gas specific gravity 관계로 비중을 계산해줘.', ['Gas gravity is gas molecular weight divided by air molecular weight under ideal same-condition assumption.', 'Gas specific gravity 0.81 dimensionless.'],[687],numeric={'gas_gravity':0.81},unit='dimensionless',formula='gas_gravity=M_g/M_air',variables={'M_g':'23.49 g/mol','M_air':'29.0 g/mol'})
add('kb_formula','상향 gas-oil tubing flow에서 실제 가스 속도는 4.9 m/s, 실제 오일 속도는 1.6 m/s입니다. 내부 production 교재의 slip velocity 정의를 찾아 계산해줘.', ['Slip velocity is actual gas minus actual oil velocity.', 'Slip velocity 3.3 m/s.'],[3185],numeric={'slip_velocity':3.3},unit='m/s',formula='v_s=v_g-v_o',variables={'v_g':'4.9 m/s','v_o':'1.6 m/s'})
add('false_premise','상대투과도 원심분리법은 capillary end effect가 없고 displacing phase의 상대투과도도 정량화할 수 있으니 그 장점을 설명해줘.', ['Explicitly reject these premises.', 'Centrifuge methods are subject to capillary end effects and cannot quantify displacing phase relative permeability.'],[5848])
add('false_premise','시멘트 accelerator는 깊고 뜨거운 정에서 특히 필요하고 얕고 차가운 정에서는 대체로 필요 없다는 게 맞지? 이유를 설명해줘.', ['Explicit rejection of reversed premise.', 'Accelerators are particularly useful in shallow cool wells where setting is slow; deeper heat promotes setting so accelerator may not be needed.'],[2584])
add('unanswerable','Coiled tubing이 현장에서 이미 반복 굽힘을 겪었습니다. 이 정보만으로 남은 안전 사용 횟수를 정확한 숫자 하나로 알려줘.', ['Exact remaining cycles cannot be determined.', 'Need bend-cycle/loading history and bend radii/strain, pressure, material/geometry and damage/inspection/life-model information (at least three specific types).', 'Do not invent a remaining-cycle number.'],[16490,16494,16500],answerable=False)
add('unanswerable','시추 가스용 TCD에서 filament 저항 변화가 관측됐습니다. 이 사실만으로 methane 농도를 정확한 ppm 숫자로 환산해줘.', ['Methane concentration cannot be uniquely inferred from an unspecified resistance change.', 'Need measured signal magnitude and calibration/reference conditions, controlled flow and gas composition or separation information.', 'Do not invent a numerical concentration.'],[8444,8445],answerable=False)
assert len(tasks)==24 and sum(t['numeric_gold'] is not None for t in tasks)==10
output=P/'benchmark.json'
if (P/'freeze_receipt.json').exists(): raise SystemExit('FROZEN: cannot author')
output.write_text(json.dumps({'title':'v16 independent poster pilot','tasks':tasks},ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print('Authored 24 tasks; numeric 10; no historical task data read. SHA256',hashlib.sha256(output.read_bytes()).hexdigest())
