# Dataset Plan --- Lloyds Green Home Score & Retrofit Recommendation Engine

## 1. Purpose

This document defines what data to collect, where to obtain it, how to
combine public sources, and how to handle missing, conflicting,
anomalous, or unavailable information.

**Agreed strategy:** Use a hybrid of public and synthetic data,
balancing realism, evaluation quality, and hackathon speed.

**Important constraints** - Build the Lloyds project independently. The
CORE repository is reference-only. - Do not assume the suggested public
datasets can be joined at property level. - Match records only when
there is a reliable basis for doing so. - Clearly distinguish observed,
derived, imputed, and synthetic values. - Never treat missing energy
usage as zero by default. - Synthetic labels and results are useful for
pipeline testing, but agreement with them alone does not demonstrate
real-world predictive accuracy. - Check the licence, permitted use,
access conditions, and date coverage of every source before using it.

## 2. Public data sources

Start with manageable subsets rather than downloading every available
record.

  --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------
  Source           Where to get it                                                                                                                     Useful fields / purpose    Limitations and       Priority
                                                                                                                                                                                  cautions              
  ---------------- ----------------------------------------------------------------------------------------------------------------------------------- -------------------------- --------------------- --------------
  Energy           [Official EPC data service](https://get-energy-performance-data.epb-integration.digital.communities.gov.uk/)                        EPC rating, property type, Certificate fields    1
  Performance                                                                                                                                          floor area,                may be missing or     
  Certificate                                                                                                                                          age/construction-related   stale. A              
  (EPC) data                                                                                                                                           fields, heating and other  recommendation on an  
                                                                                                                                                       property features where    EPC is not proof that 
                                                                                                                                                       recorded                   a retrofit was        
                                                                                                                                                                                  installed or achieved 
                                                                                                                                                                                  its predicted         
                                                                                                                                                                                  savings. Check access 
                                                                                                                                                                                  and licence terms.    

  National Energy  [Official NEED                                                                                                                      Aggregate                  Tables may be         1
  Efficiency       statistics](https://www.gov.uk/government/statistics/national-energy-efficiency-data-framework-need-consumption-data-tables-2026)   energy-consumption         aggregated rather     
  Data-Framework                                                                                                                                       benchmarks and             than property-level   
  (NEED)                                                                                                                                               relationships with         records. Use for      
                                                                                                                                                       property characteristics   calibration and       
                                                                                                                                                                                  plausibility checks,  
                                                                                                                                                                                  not as                
                                                                                                                                                                                  individual-property   
                                                                                                                                                                                  observations. Verify  
                                                                                                                                                                                  the current           
                                                                                                                                                                                  publication and table 
                                                                                                                                                                                  coverage.             

  London Smart     [London Datastore dataset](https://data.london.gov.uk/dataset/smartmeter-energy-consumption-data-in-london-households-vqm0d)        Half-hourly electricity    Historical dataset;   2
  Meter Energy                                                                                                                                         readings for household     electricity readings  
  Consumption                                                                                                                                          consumption profiles;      do not automatically  
                                                                                                                                                       annualisation and          provide matching gas, 
                                                                                                                                                       time-series experiments    EPC, retrofit or sale 
                                                                                                                                                                                  records. Start with a 
                                                                                                                                                                                  subset and document   
                                                                                                                                                                                  the date range.       

  HM Land Registry [Official Price Paid Data downloads](https://www.gov.uk/government/statistical-data-sets/price-paid-data-downloads)                 Historical sale prices,    Sales data alone      3
  Price Paid Data                                                                                                                                      transaction dates,         cannot prove a        
                                                                                                                                                       property types, tenure and retrofit caused a     
                                                                                                                                                       location/address fields as price increase.       
                                                                                                                                                       supplied                   Property-level        
                                                                                                                                                                                  matching to EPC data  
                                                                                                                                                                                  may be incomplete or  
                                                                                                                                                                                  ambiguous. Account    
                                                                                                                                                                                  for location and time 
                                                                                                                                                                                  effects.              

  Emissions        Use a suitable official UK government greenhouse-gas conversion-factor publication; record the exact publication and table used in  Electricity and gas        Factors can vary by   1
  factors          the project                                                                                                                         emissions factors in kg    year and accounting   
                                                                                                                                                       CO2e/kWh                   convention. Do not    
                                                                                                                                                                                  copy a factor without 
                                                                                                                                                                                  recording its source, 
                                                                                                                                                                                  year, unit and scope. 
  --------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------

### Initial download plan

1.  Obtain a manageable EPC subset, ideally one chosen region and a
    documented certificate-date window.
2.  Obtain relevant NEED tables to help set realistic energy-intensity
    ranges and sanity-check generated consumption.
3.  Select a manageable subset of Smart Meter households and time
    periods for electricity-profile analysis.
4.  Add Price Paid data only after deciding the valuation model's
    geographic and temporal scope.
5.  Obtain and version the emissions-factor source before calculating
    carbon impacts.

Do not spend the initial implementation period trying to force every
source into one joined table.

## 3. Canonical schema

Use an internal schema even when source datasets have different
identifiers. Keep source records and derived property records
distinguishable.

### Suggested entities

#### `properties`

-   `property_id`: internal ID, not a claim that external sources refer
    to the same property
-   `property_type`
-   `property_age_or_band`
-   `floor_area_m2`
-   `bedrooms` (if available)
-   `region` / documented geographic category
-   `energy_rating`
-   `heating_type`
-   `insulation_features`
-   `glazing_type`
-   `solar_present` and `solar_capacity_kw` (capacity only if known)
-   `smart_controls_present`
-   `current_value_estimate_gbp` (separate from historical sale prices)
-   `record_created_from`: observed / synthetic / mixed

#### `energy_usage`

-   `property_id` or source-specific household ID
-   `period_start` / `month`
-   `electricity_kwh`
-   `gas_kwh`
-   `coverage_months` or reading-coverage metadata
-   `annualisation_method`
-   `source_id`

#### `retrofit_catalogue`

-   `retrofit_id`, `name`, `category`
-   `applicability_conditions`
-   `required_existing_features`
-   `typical_energy-impact assumptions`
-   `indicative_cost_gbp` (optional; only if sourced or explicitly
    synthetic)
-   `source`, `assumptions`, `version`

#### `retrofit_history`

-   `property_id`
-   `retrofit_id`
-   `completion_date`
-   `evidence_type`: observed / inferred / synthetic

#### `sales_history`

-   `property_id` or source-specific transaction/property reference
-   `sale_date`
-   `sale_price_gbp`
-   `property_type`
-   `location_fields`
-   `source_id`
-   `match_status` and `match_method` if linked to a canonical property

#### `emissions_factors`

-   `fuel`: electricity / gas
-   `kg_co2e_per_kwh`
-   `publication`, `table`, `year`
-   `accounting_convention`
-   `retrieved_at`

#### `data_quality`

Track data quality at field or record level: - `source_id` -
`field_name` - `original_value` - `processed_value` - `status`: observed
/ derived / imputed / missing / conflicting / synthetic / rejected -
`reason` - `transformation_or_rule` - `confidence` only where it has a
defined meaning - `rule_version`

#### `model_labels`

-   `property_id`
-   `target_name`
-   `target_value`
-   `label_source`: observed / published reference / rule-generated /
    simulated
-   `label_generation_method`
-   `assumptions_version`

Adapt the schema to actual source fields. Do not assume every field
exists in every source.

## 4. Joining datasets safely

1.  Preserve original source IDs and raw source records.
2.  Create an internal `property_id` for the canonical application
    schema.
3.  Link two public records only if a reliable common identifier or
    sufficiently strong matching evidence exists.
4.  If matching by address or property attributes, define normalisation,
    matching criteria, ambiguity handling, and manual/automated quality
    checks. Do not silently accept uncertain matches.
5.  Store `match_method`, `match_status`, and relevant match evidence.
6.  Leave unmatched datasets separate and use them only for the
    modelling tasks they can support.
7.  Generate linked synthetic properties for end-to-end scenarios when
    public sources cannot be joined.
8.  Never make synthetic records appear to be real linked observations.

A canonical schema means consistent internal structure; it does **not**
mean every source must be merged into a single property-level table.

## 5. Handling missing data

Use field-specific policies. Preserve the original value and record
every transformation.

  -----------------------------------------------------------------------
  Missing or unavailable field        Recommended handling
  ----------------------------------- -----------------------------------
  Energy rating                       Do not invent an EPC rating. Mark
                                      the rating-based component
                                      unavailable and apply the
                                      documented overall-score policy for
                                      missing components.

  Floor area                          Do not calculate kWh/m² without a
                                      defensible area. Seek a reliable
                                      source; otherwise intensity and
                                      dependent rankings may be
                                      unavailable.

  Monthly energy readings             Annualise only when there is
                                      sufficient coverage and a
                                      documented method. Record months
                                      observed and assumptions. Do not
                                      silently scale a very short or
                                      unrepresentative period.

  Electricity or gas usage            Do not substitute zero unless a
                                      reliable record confirms actual
                                      zero consumption for that fuel and
                                      period. Otherwise mark missing.

  Heating, insulation or glazing      Keep unknown when evidence is
                                      absent. Impute only if a defensible
                                      method exists, preserve an
                                      imputation flag, and avoid
                                      presenting it as observed fact.

  Solar capacity                      If solar presence is known but
                                      capacity is not, use only a
                                      documented presence-based mapping
                                      or mark capacity-dependent
                                      estimates unavailable. Do not
                                      invent capacity.

  Current property value              Do not treat a historical sale
                                      price as today's value without a
                                      documented valuation method and
                                      date adjustment. If a credible
                                      baseline cannot be formed, withhold
                                      the value-impact estimate.

  Retrofit completion                 An EPC recommendation is not proof
                                      of installation. Mark completion
                                      unknown unless supported by
                                      retrofit history or other reliable
                                      evidence.

  Emissions factor                    Do not calculate carbon impact
                                      until an appropriate, documented
                                      factor is available.

  Any other optional feature          Retain null/missing status; impute
                                      only where justified and explicitly
                                      marked.
  -----------------------------------------------------------------------

### Overall score with missing components

The problem statement fixes the seven weights and final weighted-sum
formula but does not prescribe how to report a score when component
inputs are missing. Decide and document this policy before
implementation.

Preferred conservative policy: - Calculate the full score when all
required component scores are supported. - If a component is missing,
either report the overall score as unavailable or provide a clearly
labelled provisional score under a documented policy. - If renormalising
weights over available components, label the result provisional, show
coverage, and do not present it as directly comparable to a complete
seven-component score. - Never silently treat missing components as
zero.

## 6. Handling anomalies and conflicts

Implement validation checks before data enters scoring or model
training.

### Structural checks

-   Invalid or unparsable dates
-   Duplicate records and duplicate source IDs
-   Negative floor area, negative energy readings, or impossible numeric
    values
-   Unexpected units or mixed units
-   Energy-rating values outside the recognised source categories
-   Invalid property-type or heating categories
-   Monthly records outside the documented observation period

### Plausibility checks

-   Electricity/gas usage that is extreme relative to suitable
    benchmarks
-   Energy intensity that is extreme for the property's floor area and
    type
-   Floor area or bedroom count inconsistent with other records
-   Sale price that is extreme for the region, property type and date
-   Solar capacity or retrofit fields inconsistent with the available
    property evidence
-   Annualised energy values based on insufficient months

Do not automatically delete every outlier. An extreme value may be
genuine.

### Anomaly workflow

1.  **Validate:** apply schema, range and consistency checks.
2.  **Classify:** identify the issue as invalid, suspicious,
    conflicting, missing, or plausible-but-extreme.
3.  **Resolve where possible:** compare source documentation,
    timestamps, units and independent records.
4.  **Correct only with evidence:** retain the raw value and log the
    correction.
5.  **Otherwise flag or exclude:** exclude the affected field/record
    from a specific calculation or model when necessary; preserve other
    valid fields.
6.  **Record the outcome:** store the reason, action, rule version and
    source.
7.  **Test edge cases:** ensure downstream calculations and the UI
    handle flagged data safely.

Do not winsorise, clip or remove outliers without documenting the rule
and checking the impact on model performance.

## 7. Synthetic data generation

Synthetic data should supplement missing coverage and enable end-to-end
testing. It should not be arbitrary.

### Generation steps

1.  **Define a synthetic property profile.** Generate property type, age
    band, floor area, region category, EPC rating, heating, insulation,
    glazing, solar and smart-control features.
2.  **Use plausible distributions.** Where possible, calibrate category
    frequencies and numeric ranges against public EPC/NEED summaries or
    other documented sources.
3.  **Generate correlated energy use.** Condition electricity/gas
    profiles on heating type, floor area, insulation, property type and
    other defensible variables. Add seasonality where monthly data is
    generated.
4.  **Generate missingness deliberately.** Simulate realistic missing
    fields and partial meter coverage so the application can be tested
    against incomplete records.
5.  **Generate retrofit feasibility.** Apply explicit catalogue
    constraints; do not recommend every retrofit to every home.
6.  **Simulate retrofit outcomes.** Use documented formulas, published
    impact ranges, or a clearly specified simulator. Track electricity
    and gas separately.
7.  **Model interactions.** Calculate package outcomes through a
    package-level rule or simulator, not by simply summing individual
    savings.
8.  **Calculate carbon deterministically.** Use per-fuel energy changes
    and the versioned emissions-factor table.
9.  **Generate sales/valuation data cautiously.** Use documented
    relationships and plausible market variation. Do not claim that
    synthetic price changes prove causal retrofit uplift.
10. **Save generation metadata.** Record random seed, generator version,
    source distributions, formulas, assumptions and label-generation
    method.

### Suggested synthetic label hierarchy

Prefer, in order: 1. Reliable observed outcomes with suitable
provenance. 2. Published reference estimates or documented benchmarks.
3. A documented physics-inspired or rule-based simulator. 4.
Expert-defined assumptions, clearly disclosed and tested for
plausibility.

A model trained and tested only against labels created by the same rules
may merely learn those rules. Report that limitation explicitly.

## 8. Annualising energy consumption

Use one documented method consistently.

-   Sum valid monthly readings for a complete 12-month period where
    available.
-   For incomplete coverage, annualise only if coverage is sufficient
    and reasonably representative; document the number of months and
    method.
-   If seasonal coverage is biased or insufficient, mark annual
    consumption unavailable or use a validated seasonal adjustment.
-   Keep electricity and gas separate.
-   Compute intensity using the chosen consistent energy-accounting
    convention divided by floor area in m².
-   For improvement potential, use the same purchased-energy convention
    before and after retrofit: grid electricity imports plus gas
    consumed.
-   Solar reduces grid electricity imports; it does not reduce the
    home's underlying energy demand.
-   If baseline purchased energy is zero or unavailable, report
    improvement potential as unavailable, as required by the problem
    statement.

## 9. Train, validation and test data

1.  Split by property **before** fitting preprocessing, calibrating
    thresholds, or training models.
2.  Keep all records and time periods for a property in one split. If
    customer IDs or customer memory are used, split by customer where
    appropriate.
3.  Fit learned imputers and data transformations on training data only;
    apply the fitted transformations to validation and test sets.
4.  Do not use fields that would not be available at prediction time.
5.  Keep source provenance and synthetic/observed status available for
    evaluation.
6.  Evaluate on suitable held-out real observations when labels exist.
    Separately report synthetic-scenario performance.
7.  Compare against simple baselines and report limitations.
8.  Preserve a reproducible manifest of source versions, filters, split
    IDs, random seeds and code versions.

## 10. Required outputs from the data-preparation stage

Before model implementation, produce:

-   `data/raw/` --- original source files, where licence and storage
    terms permit
-   `data/processed/` --- cleaned source-specific tables
-   `data/synthetic/` --- generated linked scenarios, clearly identified
-   `data/manifests/` --- source URLs, retrieval dates, licences,
    filters and file hashes
-   `docs/data_dictionary.md` --- field names, types, units, meanings
    and availability
-   `docs/data_quality_report.md` --- missingness, anomalies, conflicts,
    exclusions and corrections
-   `docs/label_generation.md` --- how each reference label was obtained
    or generated
-   `docs/dataset_limitations.md` --- coverage, matching limitations,
    assumptions and known biases
-   Reproducible scripts for ingestion, cleaning, matching, synthetic
    generation, splitting and validation

The exact directory layout can be adjusted to the repository, but these
responsibilities should remain separate.

## 11. Definition of done

The dataset stage is ready for modelling when:

-   [ ] Sources, licences, retrieval dates and date coverage are
    documented.
-   [ ] The canonical schema and data dictionary are defined.
-   [ ] Source-specific IDs are preserved and uncertain joins are not
    forced.
-   [ ] Observed, derived, imputed, missing, conflicting and synthetic
    values are distinguishable.
-   [ ] Missingness and anomaly rules are implemented and tested.
-   [ ] Energy units and annualisation conventions are consistent.
-   [ ] Synthetic generation rules and random seeds are reproducible.
-   [ ] Retrofit labels and savings assumptions are documented.
-   [ ] Emissions factors have source, year, units and accounting
    convention.
-   [ ] Property-level train/validation/test splits prevent leakage.
-   [ ] A data-quality report and limitations document are generated.
-   [ ] The dataset can support the required outputs without silently
    fabricating unavailable estimates.

## 12. Implementation order

1.  Download and inspect EPC data and NEED tables.
2.  Define the canonical schema and data dictionary.
3.  Build source-specific cleaners and data-quality reports.
4.  Decide which records can be matched reliably; keep the rest
    separate.
5.  Add Smart Meter data for energy-profile experiments.
6.  Add Price Paid data once the valuation scope is clear.
7.  Implement missingness and anomaly handling.
8.  Build the linked synthetic generator and retrofit simulator.
9.  Create reproducible property-level splits and baseline datasets.
10. Review data quality and label validity before training models.
