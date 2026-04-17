"""
Agentic System Demo
Demonstrates the full agentic loop with web crawling and correlation analysis
"""

from agentic_loop_controller import agentic_controller, SubTask
from agentic_crawler_db import crawler_db
import time
import random

# Example task decomposer
def decompose_research_task(description: str) -> list:
    """
    Break down a complex research task into subtasks
    Example: "Research global semiconductor trends in 5 languages"
    """
    if "semiconductor" in description.lower():
        return [
            "Search English tech journals for semiconductor trends",
            "Search Japanese patent databases for chip innovations",
            "Analyze Chinese manufacturing reports",
            "Review Korean industry publications",
            "Compile German engineering standards",
            "Calculate correlation between R&D spending and output",
            "Identify unknown factors affecting chip yields",
            "Generate multilingual summary report"
        ]
    elif "climate" in description.lower():
        return [
            "Collect temperature data from weather APIs",
            "Scrape historical climate records",
            "Analyze CO2 emission patterns",
            "Find correlations with industrial activity",
            "Identify unknown contributing factors",
            "Generate predictive models"
        ]
    else:
        # Generic decomposition
        return [
            f"Research phase 1: Data collection for {description}",
            f"Research phase 2: Data analysis for {description}",
            f"Research phase 3: Correlation analysis for {description}",
            f"Research phase 4: Report generation for {description}"
        ]

# Example executor
def execute_subtask(subtask: SubTask) -> str:
    """
    Execute a single subtask
    In production, this would call actual APIs, web scrapers, etc.
    """
    print(f"   🔄 Executing: {subtask.description}")
    
    # Simulate work
    time.sleep(1)
    
    # Simulate different types of tasks
    if "search" in subtask.description.lower():
        # Simulate web crawling
        fake_url = f"https://example.com/{subtask.id}"
        fake_content = f"Research data for {subtask.description}. " * 50
        
        chunk_id = crawler_db.store_crawled_data(
            url=fake_url,
            content=fake_content,
            metadata={"source": "demo", "task_id": subtask.id}
        )
        
        return f"Crawled and stored data (chunk: {chunk_id})"
    
    elif "correlation" in subtask.description.lower():
        # Simulate correlation analysis
        dataset_a = [random.uniform(10, 100) for _ in range(20)]
        dataset_b = [a * 1.5 + random.uniform(-5, 5) for a in dataset_a]
        
        result = crawler_db.calculate_correlation(dataset_a, dataset_b)
        
        return f"Correlation analysis: R={result['r_value']:.3f}, Strength={result['strength']}"
    
    elif "identify unknown" in subtask.description.lower():
        # Simulate finding unknown correlations
        target_data = [random.uniform(50, 150) for _ in range(15)]
        
        correlations = crawler_db.find_unknown_correlations(target_data)
        
        if correlations:
            return f"Found {len(correlations)} potential correlations with unknown causes"
        else:
            return "No significant unknown correlations detected"
    
    else:
        # Generic task completion
        return f"Completed: {subtask.description}"

# Demo functions
def demo_simple_task():
    """Demo: Simple 4-step task"""
    print("\n" + "="*60)
    print("DEMO 1: Simple Research Task")
    print("="*60)
    
    job_id = agentic_controller.create_job(
        description="Research AI trends in healthcare",
        task_decomposer=decompose_research_task
    )
    
    print(f"\n📋 Job created: {job_id}")
    print("Starting execution in background...\n")
    
    agentic_controller.execute_job_async(job_id, execute_subtask)
    
    # Monitor progress
    for _ in range(10):
        time.sleep(2)
        status = agentic_controller.get_job_status(job_id)
        print(f"Progress: {status['progress']} - Status: {status['status']}")
        
        if status['status'] in ['completed', 'failed']:
            break
    
    # Show final log
    print("\n📊 Final Job Log:")
    log = agentic_controller.get_job_log(job_id)
    for entry in log:
        print(f"  Step {entry['step']}: {entry['status']} - {entry['description']}")

def demo_complex_task():
    """Demo: Complex multi-language research"""
    print("\n" + "="*60)
    print("DEMO 2: Complex Semiconductor Research (8 steps)")
    print("="*60)
    
    job_id = agentic_controller.create_job(
        description="Research global semiconductor trends in 5 languages",
        task_decomposer=decompose_research_task
    )
    
    print(f"\n📋 Job created: {job_id}")
    print("This will take ~16 seconds (8 steps × 2 sec each)")
    print("Starting execution in background...\n")
    
    agentic_controller.execute_job_async(job_id, execute_subtask)
    
    # Monitor with detailed updates
    while True:
        time.sleep(3)
        status = agentic_controller.get_job_status(job_id)
        
        print(f"\n⏱️  Progress: {status['progress']}")
        print(f"   Current: {status['current_subtask']}")
        print(f"   Status: {status['status']}")
        
        if status['summary']:
            print(f"   {status['summary']}")
        
        if status['status'] in ['completed', 'failed']:
            break
    
    print("\n✅ Job completed!")
    
    # Show database stats
    print("\n📊 Crawler Database Stats:")
    stats = crawler_db.get_stats()
    print(f"   Total chunks: {stats['total_chunks']}")
    print(f"   Total summaries: {stats['total_summaries']}")
    print(f"   Domains tracked: {stats['domains']}")

def demo_pruning():
    """Demo: Database pruning"""
    print("\n" + "="*60)
    print("DEMO 3: Database Pruning")
    print("="*60)
    
    print("\n🧹 Running database cleanup...")
    pruned = crawler_db.prune_old_data(force=True)
    print(f"   Pruned {pruned} old chunks")
    
    stats = crawler_db.get_stats()
    print(f"\n📊 Updated Stats:")
    print(f"   Remaining chunks: {stats['total_chunks']}")
    print(f"   Summaries: {stats['total_summaries']}")

def demo_job_management():
    """Demo: Job listing and management"""
    print("\n" + "="*60)
    print("DEMO 4: Job Management")
    print("="*60)
    
    print("\n📋 All Jobs:")
    jobs = agentic_controller.list_jobs()
    for job in jobs:
        print(f"   {job['job_id']}: {job['description']}")
        print(f"      Status: {job['status']} | Progress: {job['progress']}")

if __name__ == "__main__":
    print("""
╔══════════════════════════════════════════════════════════════╗
║         AGENTIC LOOP SYSTEM - DEMONSTRATION                  ║
║                                                              ║
║  Features:                                                   ║
║  • Multi-step task decomposition                            ║
║  • Asynchronous background execution                        ║
║  • Recursive summarization (every 5 steps)                  ║
║  • Web crawler database (5KB chunks)                        ║
║  • Correlation analysis (R-value calculation)               ║
║  • Automatic pruning                                        ║
╚══════════════════════════════════════════════════════════════╝
    """)
    
    # Run demos
    demo_simple_task()
    time.sleep(2)
    
    demo_complex_task()
    time.sleep(2)
    
    demo_job_management()
    time.sleep(1)
    
    demo_pruning()
    
    print("\n" + "="*60)
    print("✅ All demos completed!")
    print("="*60)

# Made with Bob
