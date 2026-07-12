## Primary SDG accuracy
```
strict   116/150 = 77.3%  (95% CI 70.0%-83.3%)  | population-weighted 77.4% (~CI 70.0%-83.4%)
dual     118/150 = 78.7%  (95% CI 71.4%-84.5%)  | population-weighted 78.9% (~CI 71.4%-84.6%)
loose    141/150 = 94.0%  (95% CI 89.0%-96.8%)  | population-weighted 94.1% (~CI 89.6%-97.2%)
```

By the model's own SDG confidence (strict):
```
high    78/96 = 81.2%  (95% CI 72.3%-87.8%)
medium  17/30 = 56.7%  (95% CI 39.2%-72.6%)
low     21/24 = 87.5%  (95% CI 69.0%-95.7%)
```

## Overseas engagement accuracy
```
overall  98/150 = 65.3%  (95% CI 57.4%-72.5%)  | population-weighted 66.6% (~CI 58.4%-73.6%)
```

Confusion matrix (rows = hand label, cols = model):
```
model_overseas_engagement  operates_directly_abroad  funds_partners_abroad  uk_fundraising_only
my_engagement                                                                                  
operates_directly_abroad                         29                      6                    1
funds_partners_abroad                            21                     31                    2
uk_fundraising_only                               7                     15                   38
```

Per-class metrics (hand labels as truth):
```
operates_directly_abroad   precision 50.9%  recall 80.6%  F1 0.62  (n=36)
funds_partners_abroad      precision 59.6%  recall 57.4%  F1 0.58  (n=54)
uk_fundraising_only        precision 92.7%  recall 63.3%  F1 0.75  (n=60)
```

By the model's own engagement confidence:
```
high    71/101 = 70.3%  (95% CI 60.8%-78.3%)
medium  15/29 = 51.7%  (95% CI 34.4%-68.6%)
low     12/20 = 60.0%  (95% CI 38.7%-78.1%)
```
