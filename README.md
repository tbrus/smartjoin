<p align="center">
  <img src="docs/logo.png">
</p>

# <span style="color: #20b5dd;">smart</span><span style="color: #81cb8b;">join</span>: data relationship discovery in seconds

Stop guessing how your tables connect. **smartjoin automatically discovers relationships between datasets** — no schema, no docs, no manual SQL detective work.

Perfect for when your data looks like this:

> *“What the hell is `cust_id_2`?”* 😵


## ✨ What SmartJoin does

SmartJoin scans your datasets and finds likely relationships between columns:

```text
orders.customer_id -> customers.id (confidence: 0.95)
payments.order_id  -> orders.id    (confidence: 0.98)
```

It works on raw files, messy tables, and unknown schemas.


## 🎯 Who is this for?

SmartJoin is built for people who live in data chaos:

* 🛠 **Data Engineers**
* 📊 **Data Analysts**
* 🤖 **ML Engineers working with raw datasets**
* 🧾 **Due diligence / consulting teams**
* 🚀 **Startups with messy data**


## ⚡ Quick Demo

```python
from smartjoin import discover_relationships

discover_relationships("./data_folder")
```

**Output:**

```text
orders.customer_id -> customers.id (confidence: 0.95)
payments.order_id  -> orders.id    (confidence: 0.98)
```


## 🐼 Pandas Integration

SmartJoin plugs straight into pandas:

```python
df.auto_join(other_df)
```

No need to remember join keys. SmartJoin figures them out for you.



## 🧠 How it works (high level)

SmartJoin uses:

* Column value overlap
* Data type similarity
* Cardinality patterns
* Statistical confidence scoring

to infer relationships automatically.


## 🔥 Why SmartJoin?

✅ Zero schema knowledge required  
✅ Works on messy real-world data  
✅ Confidence scores for every relationship  
✅ Designed for speed & exploration  
✅ Perfect for EDA and reverse-engineering databases  


## 📦 Installation (example)

```bash
pip install smartjoin
```


## 🤝 Contributing

Contributions welcome!
If SmartJoin saved you from manual joins, give it a ⭐️


## 📜 License

Licensed under the [MIT License](LICENSE)

## CLI

Use a single command to generate all primary outputs:

```bash
smartjoin run <path> <out-dir>
```

This writes:
- `<out-dir>/report.json`
- `<out-dir>/relationships.csv`
- `<out-dir>/explorer/index.html`
- `<out-dir>/explorer/data.json`

Dataset generation remains available via:

```bash
smartjoin generate-test-datasets --output-dir <output-dir>
```
