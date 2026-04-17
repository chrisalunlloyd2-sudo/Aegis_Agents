# 🤖 Agentic Loop System - Complete Guide

## Overview

The Agentic Loop System enables AI to perform **complex, multi-step reasoning** with 4 to 100+ sequential operations without context drift. It implements a **Plan → Execute → Evaluate → Summarize** cycle with asynchronous background processing.

---

## 🎯 Core Architecture

### 1. **Agentic Loop Controller** (`agentic_loop_controller.py`)

The brain of the system that manages long-running tasks.

**Key Features:**
- ✅ **Task Decomposition**: Breaks complex tasks into 4-100+ subtasks
- ✅ **Asynchronous Execution**: Runs in background with job tracking
- ✅ **Recursive Summarization**: Prevents context drift every 5 steps
- ✅ **Retry Logic**: Auto-retries failed steps (max 3 attempts)
- ✅ **Job Management**: Pause, resume, and monitor jobs

**Workflow:**
```
User Request → Task Decomposition → Background Execution
                                          ↓
                                    Execute Step 1
                                          ↓
                                    Evaluate Result
                                          ↓
                                    Success? → Next Step
                                          ↓
                                    Every 5 Steps → Recursive Summary
                                          ↓
                                    Final Compilation
```

### 2. **Crawler Database** (`agentic_crawler_db.py`)

Text-based database for organized web data with correlation analysis.

**Key Features:**
- ✅ **5KB Chunks**: Organized, compressed text storage
- ✅ **Correlation Analysis**: Calculate R-values between datasets
- ✅ **Unknown Cause Detection**: Find correlations with unidentified factors
- ✅ **Automatic Pruning**: Remove data older than 30 days
- ✅ **Domain Organization**: Group data by source domain

**Storage Structure:**
```
crawler_db/
├── chunks/          # 5KB text chunks from web crawling
├── summaries/       # Recursive summaries
├── correlations/    # R-value analysis results
├── indexes/         # Fast lookup indexes
└── metadata.json    # Database statistics
```

---

## 📊 Correlation Analysis

### Pearson R-Value Calculation

The system calculates **Pearson correlation coefficients** to find relationships between datasets:

```python
from agentic_crawler_db import crawler_db

# Example: Analyze relationship between two variables
dataset_a = [10, 20, 30, 40, 50]  # e.g., R&D spending
dataset_b = [15, 25, 35, 45, 55]  # e.g., Patent output

result = crawler_db.calculate_correlation(dataset_a, dataset_b)
print(f"R-value: {result['r_value']}")  # 1.0 = perfect correlation
print(f"Strength: {result['strength']}")  # "Very Strong"
```

**Interpretation:**
- **R ≥ 0.9**: Very Strong correlation
- **R ≥ 0.7**: Strong correlation
- **R ≥ 0.5**: Moderate correlation
- **R ≥ 0.3**: Weak correlation
- **R < 0.3**: Very Weak correlation

### Finding Unknown Correlations

Discover hidden patterns in crawled data:

```python
# Target data with unknown cause
mystery_data = [100, 105, 110, 115, 120]

# Search for correlations
correlations = crawler_db.find_unknown_correlations(mystery_data)

for corr in correlations:
    print(f"Found correlation with: {corr['url']}")
    print(f"R-value: {corr['correlation']['r_value']}")
    print(f"Potential cause: {corr['potential_cause']}")
```

---

## 🚀 Usage Examples

### Example 1: Simple Research Task

```python
from agentic_loop_controller import agentic_controller

# Define task decomposer
def decompose_task(description):
    return [
        "Collect data from source A",
        "Analyze data patterns",
        "Generate summary report"
    ]

# Define executor
def execute_step(subtask):
    # Your custom logic here
    return f"Completed: {subtask.description}"

# Create and execute job
job_id = agentic_controller.create_job(
    description="Research AI trends",
    task_decomposer=decompose_task
)

agentic_controller.execute_job_async(job_id, execute_step)

# Monitor progress
status = agentic_controller.get_job_status(job_id)
print(f"Progress: {status['progress']}")
```

### Example 2: Complex Multi-Language Research

```python
# 8-step research task
job_id = agentic_controller.create_job(
    description="Research global semiconductor trends in 5 languages",
    task_decomposer=lambda desc: [
        "Search English tech journals",
        "Search Japanese patents",
        "Analyze Chinese reports",
        "Review Korean publications",
        "Compile German standards",
        "Calculate R&D correlations",
        "Identify unknown factors",
        "Generate multilingual report"
    ]
)

# Execute in background (takes ~16 seconds)
agentic_controller.execute_job_async(job_id, execute_step)

# Job runs independently - check back later
```

### Example 3: Web Crawling with Storage

```python
from agentic_crawler_db import crawler_db

# Crawl and store data
chunk_id = crawler_db.store_crawled_data(
    url="https://example.com/article",
    content="Your crawled content here...",
    metadata={"source": "research", "topic": "AI"}
)

# Data automatically organized in 5KB chunks
print(f"Stored as chunk: {chunk_id}")
```

### Example 4: Database Pruning

```python
# Automatic cleanup of old data
pruned_count = crawler_db.prune_old_data()
print(f"Removed {pruned_count} chunks older than 30 days")

# Force prune all data
crawler_db.prune_old_data(force=True)
```

---

## 🔄 Recursive Summarization

**Problem:** By step 80 of a 100-step task, the AI forgets what was asked in step 1.

**Solution:** Every 5 steps, create a "State of the Union" summary:

```
Step 1-5 Summary:
- Collected data from 3 sources
- Identified 12 key trends
- Found correlation R=0.85

Step 6-10 Summary:
- Analyzed 500 data points
- Discovered unknown factor X
- Generated preliminary report

... continues every 5 steps
```

This prevents **context drift** in long-running tasks.

---

## 📈 Job Management

### List All Jobs

```python
jobs = agentic_controller.list_jobs()
for job in jobs:
    print(f"{job['job_id']}: {job['description']}")
    print(f"  Status: {job['status']} | Progress: {job['progress']}")
```

### Get Job Status

```python
status = agentic_controller.get_job_status(job_id)
print(f"Current step: {status['current_subtask']}")
print(f"Summary: {status['summary']}")
```

### View Detailed Log

```python
log = agentic_controller.get_job_log(job_id)
for entry in log:
    print(f"Step {entry['step']}: {entry['status']}")
    print(f"  Result: {entry['result']}")
    print(f"  Retries: {entry['retry_count']}")
```

### Pause/Resume Jobs

```python
# Pause a running job
agentic_controller.pause_job(job_id)

# Resume later
agentic_controller.resume_job(job_id, execute_step)
```

---

## 🗄️ Database Statistics

```python
stats = crawler_db.get_stats()
print(f"Total chunks: {stats['total_chunks']}")
print(f"Total summaries: {stats['total_summaries']}")
print(f"Domains tracked: {stats['domains']}")
print(f"Top domains: {stats['top_domains']}")
```

---

## 🎮 Running the Demo

Test the entire system:

```bash
python agentic_demo.py
```

**Demo includes:**
1. Simple 4-step research task
2. Complex 8-step multilingual research
3. Job management and monitoring
4. Database pruning demonstration

---

## 🔧 Configuration

### Agentic Loop Controller

```python
controller = AgenticLoopController()
controller.max_retries = 3              # Retry failed steps
controller.summary_interval = 5         # Summarize every N steps
```

### Crawler Database

```python
db = AgenticCrawlerDB()
db.max_chunk_size = 5120               # 5KB chunks
db.prune_age_days = 30                 # Auto-prune after 30 days
db.summary_interval = 5                # Summarize every 5 chunks
```

---

## 🏗️ Integration with AEGIS

To integrate with your existing AEGIS system:

```python
# In gemini_bridge_api_fast.py
from agentic_loop_controller import agentic_controller
from agentic_crawler_db import crawler_db

@app.post("/api/agentic/job")
async def create_agentic_job(data: dict):
    job_id = agentic_controller.create_job(
        description=data['task'],
        task_decomposer=your_decomposer_function
    )
    
    agentic_controller.execute_job_async(job_id, your_executor_function)
    
    return {"job_id": job_id, "status": "started"}

@app.get("/api/agentic/job/{job_id}")
async def get_job_status(job_id: str):
    return agentic_controller.get_job_status(job_id)
```

---

## 📝 Best Practices

1. **Task Decomposition**: Break tasks into 5-20 subtasks for optimal performance
2. **Executor Functions**: Keep executors focused on single operations
3. **Error Handling**: Let the retry logic handle transient failures
4. **Pruning**: Run `prune_old_data()` weekly to maintain performance
5. **Monitoring**: Check job status every 2-3 seconds for real-time updates

---

## 🚨 Troubleshooting

### Job Stuck in "Running" Status

```python
# Check detailed log
log = agentic_controller.get_job_log(job_id)
# Look for failed steps with errors
```

### Database Growing Too Large

```python
# Force prune all old data
crawler_db.prune_old_data(force=True)

# Check stats
stats = crawler_db.get_stats()
```

### Context Drift Still Occurring

```python
# Reduce summary interval
controller.summary_interval = 3  # Summarize every 3 steps instead of 5
```

---

## 🎯 Real-World Use Cases

1. **Multi-Language Research**: Crawl and analyze content in 5+ languages
2. **Market Analysis**: Correlate stock prices with news sentiment
3. **Scientific Research**: Find unknown correlations in experimental data
4. **Competitive Intelligence**: Track competitor activities across domains
5. **Trend Prediction**: Analyze historical patterns to predict future trends

---

## 📚 API Reference

### AgenticLoopController

- `create_job(description, task_decomposer)` → job_id
- `execute_job_async(job_id, executor)` → None
- `get_job_status(job_id)` → dict
- `get_job_log(job_id)` → list
- `list_jobs()` → list
- `pause_job(job_id)` → None
- `resume_job(job_id, executor)` → None

### AgenticCrawlerDB

- `store_crawled_data(url, content, metadata)` → chunk_id
- `calculate_correlation(dataset_a, dataset_b)` → dict
- `find_unknown_correlations(target_data, search_domain)` → list
- `prune_old_data(force)` → int
- `get_stats()` → dict

---

## 🔮 Future Enhancements

- [ ] Distributed execution across multiple machines
- [ ] GPU-accelerated correlation analysis
- [ ] Real-time web scraping with Selenium
- [ ] Natural language task decomposition using LLM
- [ ] Visual progress dashboard
- [ ] Export results to PDF/Excel

---

**Built for AEGIS AI System v3.8.1**  
*Enabling 100+ step reasoning without context drift*