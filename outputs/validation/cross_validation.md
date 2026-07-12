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
