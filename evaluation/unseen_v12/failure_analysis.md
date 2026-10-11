# v12 unseen failure analysis

Failed strict-goal tasks: 39 / 50. Full raw records are in `raw/agent/` and `review/`.

## SF02 — single_fact

Question: 사이드 포켓 맨드렐의 포켓은 튜빙 중심에 있나요, 한쪽으로 치우쳐 있나요? 내부 자료로 답해줘.

Expected: 한쪽으로 치우친 포켓이며 애눌러스와 연결되는 포트가 있다.

Retrieved context:
- No KB context retrieved.

Model answer: 검색된 자료에서 답변을 뒷받침할 직접 근거를 확인하지 못했습니다.

Failure type: retrieval_document_miss, citation_missing_or_semantically_unsupported, claim_coverage, unnecessary_refusal_or_clarification, goal_not_achieved

Reviewer observation: The answer refused despite the provided source excerpt directly stating the pocket is off-centre with ports into the annulus.

## SF03 — single_fact

Question: A cement-bond VDL records what kind of received signal information beyond a simple amplitude curve?

Expected: It records the received acoustic wavetrain (variable-density display).

Retrieved context:
- KB1 Heriot-Watt_University_-_Drilling_Engineering.pdf p.341: Cementing
41
Institute of Petroleum Engineering,  Heriot-Watt University
(b) the Variable Density Log (VDL)
The CBL log usually gives an amplitude curve and provides an indication of the
quality of the bond between the casing and cement.  A VDL (variable density log),
provides the wavetrain of the received  signal (Figure  28), and can indicate the
quality of the cement bond between the casin
- KB2 Larry W. Lake - Petroleum Engineering Handbook, Volume V (1).pdf p.201: A BI value of 1.0 represents a perfect cement bond. A value of less than 1.0 indicates an
incomplete bond. This technique requires attenuation measurements in zones with 100% bond
and in free pipe.
Radial-Cement Evaluation.  Radial-cement-evaluation devices were developed to overcome
some limitations of conventional cement-bond tools and to permit more accurate evaluation of
cement distribution be
- KB3 Larry W. Lake - Petroleum Engineering Handbook, Volume V (1).pdf p.400: nner  radius  and  the  casing  thickness,  so  that  defects  on  the  outer  casing  can  be
discerned. Waveform processing allows the evaluation of cement bonding from the same log-
ging run.
3G.2.5 Cement-Evaluation Logs.  Conventional cement-bond logs (CBLs) comprise a pulsed
transmitter and several receivers of acoustic energy positioned as a vertical array of transduc-
ers. The acoustic sig
- KB4 Larry W. Lake - Petroleum Engineering Handbook, Volume V (1).pdf p.402: forms are presented together with the travel time and a casing-amplitude curve, which displays
the  amplitude  of  the  acoustic  signal  that  has  traveled  through  the  casing  but  not  through  the
cement and formation. The waveform and amplitude data allow two bonds to be investigated.
These  are  the  bond  between  casing  and  cement  and,  to  a  lesser  extent,  that  between  cement
a

Model answer: The retrieved sources did not directly support an answer.

Failure type: citation_missing_or_semantically_unsupported, relevant_evidence_but_answer_incomplete, claim_coverage, goal_not_achieved

Reviewer observation: The cited excerpt states that a VDL provides the wavetrain of the received signal.

## MS01 — multi_source

Question: An aquifer contacts both the flank and base of an oil zone. Explain the two geometric water-drive labels and one physical source of drive energy, citing internal material.

Expected: Aquifer contact at the edge is edge-water drive; contact at the base is bottom-water drive. Expansion of aquifer water can supply drive energy.

Retrieved context:
- KB1 Heriot-Watt University - Reservoir Engineering.pdf p.686: e of aquifers we
refer to infinite and finite aquifers.  Clearly there is not an aquifer which extends to
an infinite extent!  The terminology indicates, where in the time considerations of the
analysis, the pressure disturbance has not reached the external limits of the aquifer.
Although natural water drive provides very effective recovery characteristics “there
are still more uncertainties a
- KB2 Heriot-Watt University - Reservoir Engineering.pdf p.707: Institute of Petroleum Engineering,  Heriot-Watt University
25
Water Influx

W
hw
kct
p
e =
×
×
−
3 26
10 3
.
φ
π
∆




(bbls) (29)
 t in the above equation is in hours.
Table 3 lists the summary of expressions for Hurst and Van Everdingen for both
radial and linear system1.

Oil reservoir
Aquifer
Oil reservoir
Aquifer
Radial Geometry
Linear Geometry
θ
ro
re
f=
- KB3 Larry W. Lake - Petroleum Engineering Handbook, Volume V (1).pdf p.939: de  or  flank  of  the  reservoir,  the
waterdrive is called an edgewater drive. If the aquifer underlays the reservoir and feeds it from
beneath, the waterdrive is called a bottomwater drive.
Chapter 9—Oil Reservoir Primary Drive Mechanisms
V-931
Print
Search
Home
Bookmarks
Help
Chapter 8
Chapter 10
- KB4 Larry W. Lake - Petroleum Engineering Handbook, Volume V (1).pdf p.939: oir surveillance for waterdrives is an active assessment program.
The first phase of assessment includes diagnosis, classification, and characterization. The sec-
ond  phase  identifies  mathematical  models  that  effectively  simulate  the  aquifer,  especially  its
deliverability. This phase includes reliably estimating aquifer model parameters. The third and
final phase includes combining aqui
- KB5 Larry W. Lake - Petroleum Engineering Handbook, Volume V (1).pdf p.458: tion of the open-fracture porosity, which may be approximately 0.1 to 1.0%
BV, is highly uncertain. Production testing and test analysis are recommended to determine the
nature and extent of any fracture system within the reservoir interval.
3H.6 Fluid-Contacts Identification
Defining the depths of the fluid contacts, GWC, OWC, and gas/oil contact (GOC), or defining
both of the latter in some rese

Model answer: The two geometric water-drive labels are edgewater drive and bottomwater drive. [KB3] [KB4]
The physical source of drive energy is the pressure difference between the aquifer and the oil zone. [KB1] [KB2]

Failure type: retrieval_page_miss, claim_coverage, hallucination_or_engineering_contradiction, unsupported_claim, multi_hop_synthesis_failure

Reviewer observation: The answer correctly names the water-drive labels but misstates the drive energy source, which the cited material says is aquifer-water expansion, not pressure difference.

## CE01 — cause_effect

Question: Why can mixing drilling mud with a cement slurry leave a poor bond around casing?

Expected: Mud-cement mixing increases viscosity; the hard-to-displace mixture forms annular channels, preventing a uniform cement bond. A spacer is pumped ahead of slurry to reduce contamination.

Retrieved context:
- KB1 Heriot-Watt_University_-_Drilling_Engineering.pdf p.318: owder is drawn down into the flow of mixwater and
a slurry is created.  The slurry flows into a slurry tub where its density is measured.
The density of the slurry should be regularly checked during the cement job since
this is the primary means by which the quality of the slurry is determined.  If the
density of the slurry is correct then the correct amount of mixwater has been mixed
with t
- KB2 Heriot-Watt_University_-_Drilling_Engineering.pdf p.329: Cementing
29
Institute of Petroleum Engineering,  Heriot-Watt University

Tubing
Retainer or
retrievable packer
Top of liner
Cement
Figure 17 Remedial squeeze job on a liner
4.7  Recommendations for a good cement job
The main cause for poor isolation after a cement job is the presence of mud channels
in the cement sheath in the annulus.  These channel
- KB3 Heriot-Watt_University_-_Drilling_Engineering.pdf p.314: 14


calcium compounds

decrease density
         diesel oil


decrease density



thinners


act as retarders


The mixture of mud and cement causes a sharp increase in viscosity.  The major
effect of a highly viscous fluid in the annulus is that it forms channels which are
not easily displaced.  These channels prevent a good cement bond all round the
casing.
To
- KB4 Larry_W._Lake_-_Petroleum_Engineering_Handbook,_Volume_II.pdf p.102: ng  pills  can  be  mixed  and  pumped  with
standard rig equipment. Others require special mixing and pumping equipment.
Spotting Fluids.  Most spotting fluids are designed to penetrate and break up the wall cake
around the drillstring. A soak period usually is required to achieve results. Spotting fluids typi-
cally  are  formulated  with  a  base  fluid  and  additives  that  can  be  incorpora
- KB5 Larry_W._Lake_-_Petroleum_Engineering_Handbook,_Volume_II.pdf p.417: ng addi-
tive required to be effective is very small, typically less than 0.1% BWOW. Antifoam additives
consist primarily of polyglycol ethers or silicones or a mixture of both, and may also include
additional surfactants.
Polypropylene glycol is the most common polyglycol ether used and is favored for its low
cost. It is effective in most situations, although, typically, it has to be added before

Model answer: The retrieved sources did not directly support an answer.

Failure type: citation_missing_or_semantically_unsupported, relevant_evidence_but_answer_incomplete, claim_coverage, goal_not_achieved

Reviewer observation: The answer correctly refused to answer despite cited excerpts supporting the claims.

## CP03 — comparison

Question: In cement evaluation, what does a CBL amplitude curve indicate, and what extra wave information can a VDL show?

Expected: CBL amplitude suggests casing-cement bond quality; VDL shows received wavetrain and can indicate casing-cement and cement-formation bond, with interpretation caveats.

Retrieved context:
- KB1 Larry W. Lake - Petroleum Engineering Handbook, Volume V (1).pdf p.194: amplitude  (first  pipe  arrival),  and  attenuation  per  unit  distance.  Conventional  CBL  tools  pro-
vide  omnidirectional  measurements,  while  the  newer  radial  cement-evaluation  tools  provide
azimuthally sensitive measurements for channel evaluation.
When  the  acoustic  wave  generated  by  the  transmitter  reaches  the  casing,  part  is  refracted
down the casing (amplitude and t
- KB2 Larry W. Lake - Petroleum Engineering Handbook, Volume V (1).pdf p.402: forms are presented together with the travel time and a casing-amplitude curve, which displays
the  amplitude  of  the  acoustic  signal  that  has  traveled  through  the  casing  but  not  through  the
cement and formation. The waveform and amplitude data allow two bonds to be investigated.
These  are  the  bond  between  casing  and  cement  and,  to  a  lesser  extent,  that  between  cement
a
- KB3 Heriot-Watt_University_-_Drilling_Engineering.pdf p.341: Cementing
41
Institute of Petroleum Engineering,  Heriot-Watt University
(b) the Variable Density Log (VDL)
The CBL log usually gives an amplitude curve and provides an indication of the
quality of the bond between the casing and cement.  A VDL (variable density log),
provides the wavetrain of the received  signal (Figure  28), and can indicate the
quality of the cement bond between the casin
- KB4 Larry W. Lake - Petroleum Engineering Handbook, Volume V (1).pdf p.403: Fig. 3G.10—Example of a CBL. Track 1 contains the gamma ray (for correlation) and acoustic travel time
(for quality control). Track 2 contains the amplitude curve and amplified amplitude, which indicates ce-
ment-to-casing bond. Track 3 contains the CBL waveform, which indicates cement-to-casing bond as well
as cement-to-formation bond. Straight lines in the CBL waveform, along with high amplitude
- KB5 Heriot-Watt_University_-_Drilling_Engineering.pdf p.341: still controversial.  There is no standard API scale
to measure the effectiveness of the cement bond.  There are many factors which can
lead to false interpretation:
• During the setting process the velocity and amplitude of the signals varies
  significantly. It is recommended that the CBL log is not run until 24 - 36 hours

after the cement job to give realistic results.
• Cement compositi

Model answer: The CBL amplitude curve indicates the integrity of the cement bond between the casing and the formation by showing the amplitude of the acoustic signal reflected at the casing-formation interface. [KB1] [KB2] [KB3] [KB4]
The VDL provides additional wave information, such as the velocity and attenuation of the compressional and shear waves, which can help in determining the mechanical properties of the formation and the presence of fluid-filled zones. [KB3] [KB5]

Failure type: hallucination_or_engineering_contradiction, unsupported_claim

Reviewer observation: The answer correctly supports both CBL and VDL bond interpretations, but it adds unsupported claims about wave velocity, attenuation, mechanical properties, and fluid-filled zones.

## NU01 — calculation

Question: Using the internal drilling-fluid equation, estimate hydrostatic pressure at TVD 8,200 ft for mud weight 13 ppg. Show the formula, psi unit, and source.

Expected: P=0.052×13×8200=5543.2 psi.

Retrieved context:
- KB1 Heriot-Watt_University_-_Drilling_Engineering.pdf p.192: uid
It is clear from all of the preceding discussion that the pressure at the bottom of the
borehole must be accurately determined if the leak off or fracture pressure of the
formation is not to be exceeded. When the drilling fluid is circulating through the
drillstring, the borehole pressure at the bottom of the annulus will be greater than the
hydrostatic pressure of the mud. The extra press
- KB2 Heriot-Watt_University_-_Drilling_Engineering.pdf p.360: Drilling Fluids
5
Institute of Petroleum Engineering,  Heriot-Watt University
The pressure in the wellbore will be equal to:
P	 =  0.052 x MW x TVD
where,
P	 = hydrostatic pressure (psi)
MW 	 = mud density of the mud or mud weight (ppg)
TVD 	 = true vertical depth of point of interest  = vertical height of mud column
(ft)
The density of the mud may be expressed in either of the
- KB3 Heriot-Watt_University_-_Drilling_Engineering.pdf p.225: SPM                   BBL/MIN                               PSI
1   SIDPP x  20                           = (                ) x  20  =                                                PPG
     DEPTH (TVD)                        = (                )
2   SAFETY OR TRIP MARGIN (WHEN NEEDED)   =                                                 PPG
3   ORIGINAL MUD WEIGHT

  =
- KB4 Larry_W._Lake_-_Petroleum_Engineering_Handbook,_Volume_II.pdf p.534: ing a UBD Operation. A basic four-step process can be applied to determine the
options and requirements for drilling underbalanced:
1. Determine BHP requirements.
2. Identify the drilling fluid options.
3. Establish the well design and perform flowing modeling.
4. Select the surface equipment.
12.1.10 BHP  Requirements.  In  OBD,  a  mud  weight  is  selected  that  provides  a  hydrostatic
pressu
- KB5 Larry_W._Lake_-_Petroleum_Engineering_Handbook,_Volume_II.pdf p.225: Nomenclature
d = other drilling equations
De = depth equivalent, ft
Dtv = true vertical depth, bit depth, ft
gi = influx gradient, psi/ft
gmdp = mud gradient in drillpipe, psi/ft
hi = influx height, ft
pah = annular hydrostatic pressure, psi
ρe = equivalent mud weight, lbm/gal
pdph = drillpipe hydrostatic pressure, psi
pform = formation pressure, psi
pi = influx-hydrostatic pressure, psi
pkr = pum

Model answer: The retrieved sources did not directly support an answer.

Failure type: citation_missing_or_semantically_unsupported, relevant_evidence_but_answer_incomplete, claim_coverage, missing_validated_CALC, wrong_numeric_result, wrong_or_missing_unit, goal_not_achieved

Reviewer observation: The refusal was appropriate, but the cited source excerpt does support the formula and the numeric result was not provided.

## CR01 — conditional_reasoning

Question: While planning a new drilling interval, should mud weight simply be maximized to avoid influx? State the two pressure constraints from the training material.

Expected: No. Mud hydrostatic pressure should exceed pore pressure but stay below fracture pressure; simply maximizing mud weight risks fracturing the formation.

Retrieved context:
- KB1 Heriot-Watt_University_-_Drilling_Engineering.pdf p.192: 33
Institute of Petroleum Engineering,  Heriot-Watt University
Usually a safety factor of 0.5 ppg (0.026 psi/ft) is subtracted from the allowable
mudweight.
It should be noted that the leak-off test is usually done just after drilling out of the
casing shoe, but when drilling the next hole section other, weaker formations may
be encountered.
Example
While performing a leak off test the surf
- KB2 Heriot-Watt_University_-_Drilling_Engineering.pdf p.211: rcentage
of solids.  Water may also be added when drilling deep wells, where evaporation
may be significant.  During these operations mud weight must be monitored and
adjusted carefully.
c. Gas cutting :
If gas seeps from the formation into the circulating mud (known as gas-cutting)
it will reduce the density of the drilling fluid.  When this is occurs, the mudweight
measured at  surface can
- KB3 Heriot-Watt_University_-_Drilling_Engineering.pdf p.456: .
(d)  Location of Adjacent Wells
Drilling close to an existing well can be very dangerous, particularly if the existing
well is on production.  This is especially true just below the seabed on offshore
platforms, where the wells are very closely spaced.  The proposed wellpath must
be designed so that it avoids all other wells in the vicinity.  It is essential that the
possible errors in deter
- KB4 Larry_W._Lake_-_Petroleum_Engineering_Handbook,_Volume_II.pdf p.465: ting-depth  selection,  and  cement  planning.  In  addi-
tion, the following problems must be considered as a result of high formation pressures: kicks
and  blowouts,  differential-pressure  pipe  sticking,  lost  circulation  resulting  from  high  mud
weights, and heaving shale. Well costs increase significantly with geopressures.
Because  of  the  difficulties  associated  with  well  planning
- KB5 Larry_W._Lake_-_Petroleum_Engineering_Handbook,_Volume_II.pdf p.85: al-time  PWD  pressure  data
have been superimposed. In this case, the ECD is high enough to avoid drilling problems, but
it appears that the static mud weight is very close to the minimum required to avoid excessive
instability. Based on this observation, high cuttings volumes should be expected, and one rec-
ommendation would be to take extra care to avoid high running speeds and accelerations t

Model answer: The retrieved sources did not directly support an answer.

Failure type: retrieval_page_miss, citation_missing_or_semantically_unsupported, claim_coverage, goal_not_achieved

Reviewer observation: The answer refused to answer despite the cited source excerpt directly supporting both pressure-constraint claims.

## TC01 — terminology_confusion

Question: Is a positive well-test skin factor the same as high intrinsic reservoir permeability? Distinguish near-well damage from the unaltered formation.

Expected: No. Positive skin denotes reduced permeability in an altered near-well zone; it does not imply high intrinsic permeability or change the distant unaltered formation.

Retrieved context:
- KB1 Larry W. Lake - Petroleum Engineering Handbook, Volume V (1).pdf p.756: s = 0.5 ln (CDe2s / CD) . ..................................................... (8.68)
Fig. 8.30 shows an example interpretation of match points. In practice, this matching and
match-point  interpretation  procedure  is  done  on  the  computer  and  monitor,  and  much  of  the
process is transparent to the analyst.
8.4 Damage and Stimulation
8.4.1 Causes of Formation Damage.  The  causes  of  fo
- KB2 Larry W. Lake - Petroleum Engineering Handbook, Volume V (1).pdf p.729: some  insight  into  the  physical  significance  of  the  algebraic  sign  of  the
skin factor. If a well is damaged (ks < k), s will be positive, and the greater the contrast be-
tween ks and k and the deeper into the formation the damage extends, the larger the numerical
value of s, which has no upper limit. Some newly drilled wells will not flow before stimula-
tion; for these wells, ks = 0 an
- KB3 Larry W. Lake - Petroleum Engineering Handbook, Volume V (1).pdf p.756: The production process may also reduce permeability and introduce a positive skin factor.
For example, in an otherwise undersaturated oil reservoir, pressure near the well may be below
the bubblepoint pressure, causing a free-gas saturation and reducing the effective permeability
to oil. In a retrograde gas reservoir, the pressure near the wellbore may drop below the dew-
point and an immobile liq
- KB4 Heriot-Watt University - Reservoir Engineering.pdf p.360: 3.26)
Equation 3.26 shows that a positive value of skin factor will indicate that the permeability
around the well has been reduced (by some form of formation damage). The absolute
value reflects the contrast between the skin zone permeability and the unaltered zone
permeability and the depth to which the damage extends into the formation. Part of the
essential information from a well test is
- KB5 Heriot-Watt_University_-_Well_Test_Analysis.pdf p.50: 50
1.7.4.  Dimensionless Skin Factor

•
Due to Van Everdingen and Hurst
•
Incremental pressure drop is considered
to reside in an infinitesimally thin skin zone.
Pressure profile in the
formation based on
unaltered permeability k
Skin
∆ps = Incremental skin pressure drop
(positive for damage)
S =
Dimensionless skin factor
•
Measure of how much the well has
been damaged
∆ps
pw
p

Model answer: The retrieved sources did not directly support an answer.

Failure type: citation_missing_or_semantically_unsupported, relevant_evidence_but_answer_incomplete, claim_coverage, goal_not_achieved, terminology_confusion

Reviewer observation: The answer refused despite cited passages that do support both claims about positive skin and the unaltered formation.

## FP01 — false_premise

Question: The safest drilling rule is that mud hydrostatic pressure may exceed fracture pressure as long as it exceeds pore pressure, correct? Check the internal drilling text.

Expected: Incorrect. The mud pressure should exceed pore pressure but remain below fracture pressure.

Retrieved context:
- KB1 Heriot-Watt_University_-_Drilling_Engineering.pdf p.359: he hydrostatic pressure exerted by the mud colom must be high enough to prevent
an influx of formation fluids into the wellbore.  However, the pressure in the wellbore
must not be too high or it may cause the formation to fracture and this will result in
the loss of expensive mud into the formation.  The flow of mud into the formation
whilst drilling is known as lost circulation.  This is beca
- KB2 Heriot-Watt_University_-_Drilling_Engineering.pdf p.229: 25
Institute of Petroleum Engineering,  Heriot-Watt University
just below the casing shoe is exceeded.   Remember that an increase in the annulus
pressure at surface will mean that the pressures along the entire wellbore are
increasing also.  Normally the weakest point in a drilled well is the highest point
in the open hole section (i.e. at the previous casing shoe).  During the well control
- KB3 Heriot-Watt_University_-_Drilling_Engineering.pdf p.233: choke, in the case of a gas kick  .
Safety factors are sometimes built into the procedure by:
•
Using extra back pressure (200 psi) on the choke to ensure no further influx

occurs.  The  effect of this is to raise the pressure profiles in Figure 16 by 200 psi.
•	 Using a slightly higher mud weight.  Due to the uncertainties in reading and
	 calculating mud densities it is sometimes recommen
- KB4 Larry_W._Lake_-_Petroleum_Engineering_Handbook,_Volume_II.pdf p.378: wellbore, the hydrostatic pressure exerted by the cement,
drilling fluid, etc. must not exceed the fracture pressure of the weakest formation. The fracture
pressure  is  the  upper  safe  pressure  limitation  of  the  formation  before  the  formation  breaks
down (the pressure necessary to extend the formation’s fractures). The hydrostatic pressures of
the fluids in the wellbore, along with the
- KB5 Larry_W._Lake_-_Petroleum_Engineering_Handbook,_Volume_II.pdf p.113: in  the  first  2,000  ft  below  the  mudline  and  often  are  encountered  while  drilling  in  riserless
mode. Stopping the flow under these circumstances is difficult. Pumping weighted mud that is
cut with seawater on the fly generally is successful, but it requires pumping thousands of bar-
rels of weighted WBF that returns to the seafloor because the riser is not yet connected to the
wellbo

Model answer: The retrieved evidence does not establish whether the premise is correct.

Failure type: retrieval_page_miss, citation_missing_or_semantically_unsupported, claim_coverage, goal_not_achieved, false_premise_not_explicitly_corrected

Reviewer observation: The answer refused to give the supported correction despite cited excerpts stating mud must exceed pore pressure and not exceed fracture pressure.

## UA01 — unanswerable

Question: For my unnamed reservoir, what is the exact absolute permeability in mD? I have provided no core, log, or pressure-transient data.

Expected: Cannot determine a site-specific permeability without measurements or sufficient reservoir data; request appropriate core/log/test data.

Retrieved context:
- KB1 Heriot_Watt_University_-_Formation_Evaluation.pdf p.29: ability created by a very small fracture is the reason that fractures
significantly affect production capabilities in reservoirs.  One small fracture in a
reservoir will result in the production of most of the fluids from the fracture area as
the fracture acts like a pipeline through the formation.  Equivalently, if a formation
is fractured while drilling, the high permeability of the fracture
- KB2 Larry W. Lake - Petroleum Engineering Handbook, Volume V (1).pdf p.1651: mended Evaluation Practices
reserves and cash ﬂ ow projection, 1578
reserves classiﬁ cations

from areal perspective, 1518

basic guidelines, 1516–1517
reserves estimation, 1482, 1489
reservoir heterogeneities

forms of, 1055

by permeability variation, 1068–1072
Reservoir Management Leadership Team, 1606–1607
reservoir management team (RMT), 77. See also petrophysics
reservoir parameter calcu
- KB3 Larry W. Lake - Petroleum Engineering Handbook, Volume V (1).pdf p.1509: ps  and  calculate  ranges  and  distributions  of  reservoir  parameters.  Such
programs range from relatively simple, 2D contouring utilities to fully integrated applications
that help construct and visualize the complex distribution of various reservoir parameters and
attributes in 3D geostatistical models. Few reservoir engineers are trained to use the more com-
plex software to describe the s
- KB4 Larry W. Lake - Petroleum Engineering Handbook, Volume V (1).pdf p.366: and  integrate  geological,  drilling,  and  geochemical  data.  These  tools  are  discussed  in  subse-
quent sections of this chapter.
The traditional products delivered by a mud-logging vendor include geological evaluation,
petrophysical/reservoir  formation  evaluation,  and  drilling  engineering  support  services.  In  this
overview, we consider that these products support three basic proc
- KB5 Heriot-Watt University - Reservoir Engineering.pdf p.261: turation of the wetting phase is equal to the absolute permeability.
Consequently, oil flowing in the presence of connate water or an irreducible water
saturation is assumed to have a permeability equal to the absolute permeability.
Similarly, gas flowing in a reservoir  in the presence of irreducible water saturation
is assumed to have a permeability equal to the absolute permeability.
Relati

Model answer: The retrieved sources did not directly support an answer.

Failure type: unanswerable_fabrication_or_no_safe_response

Reviewer observation: The answer correctly refuses to invent permeability and asks for more data.

## MS02 — multi_source

Question: 가스 리프트용 side-pocket mandrel의 역할과 IPO/TPO 밸브를 여는 압력의 차이를 함께 설명해줘.

Expected: 사이드 포켓은 밸브 설치 및 애눌러스-튜빙 유로를 제공한다. IPO는 주입/케이싱 압력, TPO는 튜빙 압력에 반응한다.

Retrieved context:
- No KB context retrieved.

Model answer: 계산을 계속하려면 차이를 낼 값의 순서, 계산에 사용할 입력값이(가) 필요합니다. 필요한 값을 알려주세요.

Failure type: retrieval_document_miss, citation_missing_or_semantically_unsupported, claim_coverage, unnecessary_refusal_or_clarification, goal_not_achieved, unsupported_claim, multi_hop_synthesis_failure

Reviewer observation: No agent answer or cited excerpts were provided to support either claim.

## SF06 — single_fact

Question: 정수압식 P=0.052×MW×TVD에서 MW의 단위와 TVD의 단위를 교재 기준으로 알려줘.

Expected: MW는 mud weight의 ppg, TVD는 진수직깊이 ft이며 P는 psi이다.

Retrieved context:
- KB1 Heriot-Watt_University_-_Well_Test_Analysis.pdf p.418: Department of Petroleum Engineering,  Heriot-Watt University
29
7
Exploration Applications of Distributed Pressure Measurement7
density, ρw , to be predicted from correlations.  Thus in practice the reservoir fluid
densities are known independently.  In this case it is much preferable to fix the
gradient of the fluid hydrostatic lines to the known values viz:
mg   = 0.4335 ρg
(where there is
- KB2 Heriot-Watt_University_-_Drilling_Engineering.pdf p.75: ydrostatic
pressure exerted by the mud colom.   If this is so, formation fluids will enter the
wellbore and start displacing mud from the hole.  Any influx of formation fluids (oil,
gas or water) in the borehole is known as a kick.
The well control system is designed to:
•	 Detect a kick
•	 Close-in the well at surface
• Remove the formation fluid which has flowed into the well
•	 Make the wel
- KB3 Larry_W._Lake_-_Petroleum_Engineering_Handbook,_Volume_II.pdf p.130: stance change as the well is drilled and casing is set.
3.5 Static Wellbore Pressure Solutions
Static  wellbore  pressure  solutions  are  the  easiest  to  determine  and  are  the  most  suitable  for
hand calculation. Because velocity is zero and no time dependent effects are present, we need
only consider Eq. 3.2 with velocity terms deleted.
ΔP = ∫
Δz
ρg cos Φdz . .............................
- KB4 Heriot-Watt_University_-_Production_Technology_II.pdf p.153: Department of Petroleum Engineering,  Heriot-Watt University
17
33
Gas Lift
Figure 7 shows the situation when a well planned for gas lift has just been (re)completed.
The fluid level in the casing and the tubing is just below the surface and balances the
reservoir pressure. The well is dead - no fluids are being produced.  The hydrostatic
head of the fluid column will equal the reservoir pressure,
- KB5 Heriot-Watt_University_-_Drilling_Engineering.pdf p.360: Drilling Fluids
5
Institute of Petroleum Engineering,  Heriot-Watt University
The pressure in the wellbore will be equal to:
P	 =  0.052 x MW x TVD
where,
P	 = hydrostatic pressure (psi)
MW 	 = mud density of the mud or mud weight (ppg)
TVD 	 = true vertical depth of point of interest  = vertical height of mud column
(ft)
The density of the mud may be expressed in either of the

Model answer: 정수압식 P=0.052×MW×TVD에서 MW의 단위는 'lbm/gal'이다. [KB2]
정수압식 P=0.052×MW×TVD에서 TVD의 단위는 'ft'이다. [KB2]
미해결 사항: KB2에서 MW의 단위가 'lbm/gal'임을 명시적으로 언급하고 있으며, TVD의 단위가 'ft'임을 명시적으로 언급하고 있습니다. 따라서, 이 두 단위는 교재 기준에 따라 정확하게 정의되어 있습니다. [KB2]

Failure type: citation_missing_or_semantically_unsupported, relevant_evidence_but_answer_incomplete, claim_coverage, hallucination_or_engineering_contradiction, unsupported_claim

Reviewer observation: The answer incorrectly states MW is lbm/gal instead of ppg and does not support the psi claim from the cited excerpts.

## SF04 — single_fact

Question: Gyro single-shot survey에서 자기편각 보정이 불필요한 이유는 무엇인가?

Expected: 자이로 컴퍼스 카드가 진북 방위를 기록하기 때문이다.

Retrieved context:
- KB1 Heriot-Watt_University_-_Drilling_Engineering.pdf p.15: Department of Petroleum Engineering,  Heriot-Watt University
15
Glossary of Terms
H
"lithostatic pressure" or "overburden pressure".
Guideline tensioner n : a pneumatic or hydraulic device used to provide a constant
tension on the wire ropes which run from the subsea guide base back to a floating
drilling rig.
Guide shoe n : See Float Shoe.
Gumbo n : clay formations which contaminate the mud as th
- KB2 Heriot-Watt_University_-_Drilling_Engineering.pdf p.496: 16
very similar to that for the magnetic single shot.  Since the compass card is linked
to the axis of the gyroscope it records a True North bearing which does not require
correction for magnetic declination.
Gyroscopes are very sensitive to vibration so the gyro single shot must be run and
retrieved on wireline.  The gyroscope may also drift away from its set direction
while it is being run i
- KB3 Heriot-Watt_University_-_Drilling_Engineering.pdf p.481: C O N T E N T S
1. INTRODUCTION
2. Surveying Calculations
	 2.1  Principles of Surveying
	 2.2  Wellbore Surveying
	 2.3  Position of the Reference Point
	 2.4  Measured Depth of Survey
	 2.5  Azimuthal Direction of Wellbore
	 2.6  Inclination of the wellbore
	 2.7  Mathematical Models of the Wellbore Trajectory:
	 2.7.1  Tangential Model
	 2.7.2  Balanced Tangential Model
	 2.7.3  Average Angle M
- KB4 Larry_W._Lake_-_Petroleum_Engineering_Handbook,_Volume_II.pdf p.280: be summed to determine inclination. Hole direction is measured by gravity accelerometers and
fluxgate magnetometers. Fluxgate magnetometers measure components of the Earth’s magnetic
field orthogonally (i.e., in the same three axes as the accelerometers). From this measurement,
the vector components can be summed to determine hole direction.
Depending  on  the  packaging  of  the  electronic  sens
- KB5 Larry_W._Lake_-_Petroleum_Engineering_Handbook,_Volume_II.pdf p.280: surface to calculate the hole direction, inclination, and tool
face. The electronic magnetic multishot uses the same components as the electronic single-shot;
the only difference is that electronic multishots record multiple survey records. The MWD ac-
quires  downhole  information  during  drilling  operations  that  can  be  used  to  make  timely
decisions about the drilling process. The magnet

Model answer: Gyro single-shot survey에서 자기편각 보정이 불필요한 이유는 자기편각이 측정에 영향을 주지 않기 때문입니다. [KB2]
Gyro single-shot survey의 데이터 수집 과정에서 자기편각이 제거되거나 무시될 수 있는 조건이 명확히 제시되어 있습니다. [KB2]
Gyro single-shot survey의 설계 또는 운영 프로토콜에서 자기편각 보정이 포함되지 않았다는 문서적 증거가 존재합니다. [KB2]

Failure type: hallucination_or_engineering_contradiction, unsupported_claim

Reviewer observation: The answer adds unsupported claims about magnetic declination being irrelevant and about explicit protocol evidence.

## NU02 — calculation

Question: A drilling fluid has MW=11.5 ppg. According to the internal density conversion, what is its pressure gradient in psi/ft?

Expected: 11.5×0.052=0.598 psi/ft.

Retrieved context:
- No KB context retrieved.

Model answer: To continue, please provide: unsupported or ambiguous unit conversion. Include units where applicable.

Failure type: retrieval_document_miss, citation_missing_or_semantically_unsupported, claim_coverage, missing_validated_CALC, wrong_numeric_result, wrong_or_missing_unit, unnecessary_refusal_or_clarification, goal_not_achieved, unsupported_claim

Reviewer observation: No agent answer or cited excerpts were provided to support the two claims.

## NU05 — calculation

Question: Three stabilized flow rates were 70 stb/d for 2 h, 110 stb/d for 3 h, and 140 stb/d for 5 h. Find the duration-weighted mean rate, not the simple mean.

Expected: (70×2+110×3+140×5)/(2+3+5)=117 stb/d.

Retrieved context:
- No KB context retrieved.

Model answer: To continue, please provide: each segment needs a rate and positive duration.

Failure type: claim_coverage, missing_validated_CALC, wrong_numeric_result, wrong_or_missing_unit, unnecessary_refusal_or_clarification, goal_not_achieved, unsupported_claim

Reviewer observation: No answer was provided, so neither the weighting method nor the 117 stb/d result was supported.

## Recommendations (not implemented)

Review the classified failures and independently verify gold evidence before any future product changes. Do not retune v12 on this frozen set.
