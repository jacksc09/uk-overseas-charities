## Cross-validation against register classification codes

Population: all 19,688 tagged charities. The register codes are self-reported tick-boxes the classifier never saw; this is agreement between two imperfect signals, not a measure of accuracy.

### "Overseas Aid/famine Relief" vs model overseas-active

```
                  register_aid=yes  register_aid=no
model_active=yes              4005            10336
model_active=no                864             4483

raw agreement 43.1%, Cohen's kappa 0.08
```

Where the register box IS ticked (n=4,869), the model calls the charity overseas-active 82.3% of the time.
Share of each model class that ticked the box (expect both overseas classes well above uk_fundraising_only):
```
overseas_engagement
funds_partners_abroad       25.3%
operates_directly_abroad    30.2%
uk_fundraising_only         16.2%
```

### "Makes Grants To Organisations" vs model funds_partners_abroad

```
                 register_grants=yes  register_grants=no
model_funds=yes                 4419                2108
model_funds=no                  5650                7511

raw agreement 60.6%, Cohen's kappa 0.22
```

Share of each model class that ticked the grant-making box (expect funds_partners_abroad highest):
```
overseas_engagement
funds_partners_abroad       67.7%
operates_directly_abroad    42.0%
uk_fundraising_only         44.3%
```

### Register countries listed, by model class

Mean and median number of overseas countries each class has in the register's area-of-operation table:
```
                          mean  median  count
overseas_engagement                          
funds_partners_abroad      4.6     1.0   6527
operates_directly_abroad   6.2     1.0   7814
uk_fundraising_only        6.7     2.0   5347
```

### IATI publishers vs model overseas-active (post hoc, one-sided)

Added 2026-08-15, after the pre-registered protocol was scored, so it is a post-hoc check. IATI is the open standard aid organisations use to publish what they fund and where; publishing is often a condition of FCDO funding. Publishing therefore says a charity is in the official aid-delivery chain - not, strictly, that it runs projects abroad - and the check is one-sided: not publishing says nothing (most small charities have no reason to). It is also incomplete: only publishers who declare their charity number are matched, so charities that publish under a company number are not counted (they are listed in data/iati_manifest.json). It is a third convergent signal on a small, large-charity subset, not an accuracy figure; the hand-labelled sample remains the only accuracy measure.

Of the 200 charities in the dataset that publish to IATI under their charity number (median income £2,954,688, against 66% of the whole population under £100,000), the model calls 187 overseas-active: **93.5%** (Wilson 95% CI 89.2%-96.2%).

Model class among IATI publishers:
```
overseas_engagement
operates_directly_abroad    145
funds_partners_abroad        42
uk_fundraising_only          13
```

The 13 IATI publishers the model called uk_fundraising_only, judged from the same text the model saw:

- **text-sparse** (7): register text describes UK-focused or generic work with no overseas mechanism - the flag's documented fallback behaviour
  - Zing (1133342)
  - Near East Foundation Uk (1150993)
  - Royal Society For The Protection Of Birds (207076)
  - The Royal National Lifeboat Institution (209603)
  - Royal College Of Obstetricians And Gynaecologists (213280)
  - Education Development Trust (270901)
  - The National Foundation For Educational Research In England And Wales (313392)
- **policy-intermediary** (6): text IS explicitly international, but the charity advises, convenes or researches rather than running or funding projects abroad - a boundary case the three-way taxonomy does not cleanly hold
  - Saferworld (1043843)
  - The Climate Change Organisation (1102909)
  - Climate Bonds Initiative (1154413)
  - The Royal United Services Institute For Defence And Security Studies (210639)
  - Odi Global (228248)
  - The Centre For Lebanese Studies (298375)
