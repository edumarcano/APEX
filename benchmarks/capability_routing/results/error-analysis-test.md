# Capability routing held-out failure analysis

- Router: `hybrid-minilm-onnx`
- Split: `test`
- Total failures: 16
- Label corrections applied: [{'case_id': 'market-false-friend-1', 'original': ['weather'], 'corrected': ['none'], 'justification': 'false_friend difficulty; prompt uses weather wording without forecast intent and matches other false_friend none labels.'}]

## Failure patterns (top 10)

- (8x) multi_family; missing=todo; irrelevant=-; fallback=partial_coverage; cap=False; origin=handwritten
- (4x) search; missing=search; irrelevant=-; fallback=low_confidence_fallback; cap=False; origin=synthetic
- (3x) todo; missing=todo; irrelevant=-; fallback=low_confidence_fallback; cap=False; origin=synthetic
- (1x) mail; missing=mail; irrelevant=-; fallback=low_confidence_fallback; cap=False; origin=synthetic

## Grouped failures

### mail|expected=1|fallback=low_confidence_fallback|cap=False|origin=synthetic (1 cases)
- `pad-315` (synthetic): expected=['mail'] selected=[] top=0.34688036685497053 margin=0.08835295031708801

### multi_family|expected=2|fallback=partial_coverage|cap=False|origin=handwritten (8 cases)
- `multi-todo-sched-1-240` (handwritten): expected=['schedule', 'todo'] selected=['schedule'] top=0.6076302483173183 margin=0.2943815543742946
- `multi-todo-sched-1-245` (handwritten): expected=['schedule', 'todo'] selected=['schedule'] top=0.6076302483173183 margin=0.2943815543742946
- `multi-todo-sched-1-250` (handwritten): expected=['schedule', 'todo'] selected=['schedule'] top=0.6076302483173183 margin=0.2943815543742946
- `multi-todo-sched-1-255` (handwritten): expected=['schedule', 'todo'] selected=['schedule'] top=0.6076302483173183 margin=0.2943815543742946
- `multi-todo-sched-1-260` (handwritten): expected=['schedule', 'todo'] selected=['schedule'] top=0.6076302483173183 margin=0.2943815543742946
- ... and 3 more

### search|expected=1|fallback=low_confidence_fallback|cap=False|origin=synthetic (4 cases)
- `search-auto-76` (synthetic): expected=['search'] selected=[] top=0.44637912619473297 margin=0.17423926694088038
- `search-auto-80` (synthetic): expected=['search'] selected=[] top=0.4402886731274146 margin=0.15577822747829834
- `search-auto-83` (synthetic): expected=['search'] selected=[] top=0.4235448251998599 margin=0.1323422084539419
- `search-auto-86` (synthetic): expected=['search'] selected=[] top=0.40572536099316436 margin=0.1261411200254446

### todo|expected=1|fallback=low_confidence_fallback|cap=False|origin=synthetic (3 cases)
- `todo-auto-126` (synthetic): expected=['todo'] selected=[] top=0.3825226179186115 margin=0.07324423699346372
- `todo-auto-129` (synthetic): expected=['todo'] selected=[] top=0.41467974100744814 margin=0.10490741639104673
- `todo-auto-135` (synthetic): expected=['todo'] selected=[] top=0.3826828650060901 margin=0.05577098636594602
