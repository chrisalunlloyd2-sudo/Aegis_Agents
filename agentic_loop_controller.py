"""
Agentic Loop Controller v1.0
- Multi-step task decomposition (Plan → Execute → Evaluate → Summarize)
- Asynchronous background execution with job tracking
- Recursive summarization to prevent context drift
- Integration with crawler database
"""

import asyncio
import json
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Callable
from enum import Enum
from dataclasses import dataclass, asdict
import threading

class TaskStatus(Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"

@dataclass
class SubTask:
    id: str
    description: str
    status: TaskStatus
    result: Optional[str] = None
    error: Optional[str] = None
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    retry_count: int = 0

@dataclass
class AgenticJob:
    job_id: str
    description: str
    status: TaskStatus
    subtasks: List[SubTask]
    current_step: int
    total_steps: int
    created_at: str
    started_at: Optional[str] = None
    completed_at: Optional[str] = None
    summary: Optional[str] = None
    final_result: Optional[str] = None

class AgenticLoopController:
    def __init__(self, jobs_dir: str = "agentic_jobs"):
        self.jobs_dir = Path(jobs_dir)
        self.jobs_dir.mkdir(exist_ok=True)

        self.active_jobs: Dict[str, AgenticJob] = {}
        self.job_threads: Dict[str, threading.Thread] = {}
        self.lock = threading.RLock()

        # Configuration
        self.max_retries = 3
        self.summary_interval = 5  # Summarize every 5 steps

        # Load existing jobs
        self._load_jobs()

    def _load_jobs(self):
        """Load existing jobs from disk"""
        for job_file in self.jobs_dir.glob("*.json"):
            try:
                with open(job_file, 'r', encoding='utf-8') as f:
                    job_data = json.load(f)

                subtasks = [self._subtask_from_dict(st) for st in job_data["subtasks"]]
                job = AgenticJob(
                    job_id=job_data["job_id"],
                    description=job_data["description"],
                    status=TaskStatus(job_data["status"]),
                    subtasks=subtasks,
                    current_step=job_data["current_step"],
                    total_steps=job_data["total_steps"],
                    created_at=job_data["created_at"],
                    started_at=job_data.get("started_at"),
                    completed_at=job_data.get("completed_at"),
                    summary=job_data.get("summary"),
                    final_result=job_data.get("final_result")
                )
                self.active_jobs[job.job_id] = job
            except Exception as e:
                print(f"⚠️ Skipping unreadable job file {job_file.name}: {e}")

    def _subtask_to_dict(self, subtask: SubTask) -> Dict:
        return {
            "id": subtask.id,
            "description": subtask.description,
            "status": subtask.status.value,
            "result": subtask.result,
            "error": subtask.error,
            "started_at": subtask.started_at,
            "completed_at": subtask.completed_at,
            "retry_count": subtask.retry_count,
        }

    def _subtask_from_dict(self, data: Dict) -> SubTask:
        payload = dict(data)
        payload["status"] = TaskStatus(payload["status"])
        return SubTask(**payload)

    def _save_job(self, job: AgenticJob):
        """Save job to disk"""
        job_file = self.jobs_dir / f"{job.job_id}.json"

        # Convert to dict
        job_dict = {
            "job_id": job.job_id,
            "description": job.description,
            "status": job.status.value,
            "subtasks": [self._subtask_to_dict(st) for st in job.subtasks],
            "current_step": job.current_step,
            "total_steps": job.total_steps,
            "created_at": job.created_at,
            "started_at": job.started_at,
            "completed_at": job.completed_at,
            "summary": job.summary,
            "final_result": job.final_result
        }

        with self.lock:
            with open(job_file, 'w', encoding='utf-8') as f:
                json.dump(job_dict, f, indent=2)

    def create_job(self, description: str, task_decomposer: Callable[[str], List[str]]) -> str:
        """
        Create a new agentic job

        Args:
            description: High-level task description
            task_decomposer: Function that breaks task into subtasks

        Returns:
            job_id for tracking
        """
        job_id = str(uuid.uuid4())[:8]

        # Decompose task into subtasks
        subtask_descriptions = task_decomposer(description)

        subtasks = [
            SubTask(
                id=f"{job_id}_step_{i+1}",
                description=desc,
                status=TaskStatus.PENDING
            )
            for i, desc in enumerate(subtask_descriptions)
        ]

        job = AgenticJob(
            job_id=job_id,
            description=description,
            status=TaskStatus.PENDING,
            subtasks=subtasks,
            current_step=0,
            total_steps=len(subtasks),
            created_at=datetime.now().isoformat()
        )

        with self.lock:
            self.active_jobs[job_id] = job
            self._save_job(job)

        print(f"✅ Created job {job_id}: {description}")
        print(f"   Decomposed into {len(subtasks)} subtasks")

        return job_id

    def execute_job_async(self, job_id: str, executor: Callable[[SubTask], str]):
        """
        Execute job asynchronously in background

        Args:
            job_id: Job to execute
            executor: Function that executes a single subtask
        """
        if job_id not in self.active_jobs:
            raise ValueError(f"Job {job_id} not found")

        job = self.active_jobs[job_id]

        existing_thread = self.job_threads.get(job_id)
        if existing_thread and existing_thread.is_alive():
            print(f"⚠️ Job {job_id} is already running")
            return

        if job.status == TaskStatus.COMPLETED:
            print(f"⚠️ Job {job_id} is already completed")
            return

        if job.status == TaskStatus.FAILED:
            remaining = [st for st in job.subtasks if st.status != TaskStatus.COMPLETED]
            if not remaining:
                print(f"⚠️ Job {job_id} has no remaining work")
                return

        # Start background thread
        thread = threading.Thread(
            target=self._execute_job_loop,
            args=(job_id, executor),
            daemon=True
        )
        self.job_threads[job_id] = thread
        thread.start()

        print(f"🚀 Started job {job_id} in background")

    def _execute_job_loop(self, job_id: str, executor: Callable[[SubTask], str]):
        """
        Main execution loop (runs in background thread)
        Implements: Plan → Execute → Evaluate → Summarize
        """
        job = self.active_jobs[job_id]
        with self.lock:
            if not job.started_at:
                job.started_at = datetime.now().isoformat()
            job.status = TaskStatus.RUNNING
            self._save_job(job)

        print(f"\n{'='*60}")
        print(f"🎯 STARTING AGENTIC LOOP: {job.description}")
        print(f"{'='*60}\n")

        for i in range(job.current_step, job.total_steps):
            job = self.active_jobs[job_id]
            subtask = job.subtasks[i]

            if subtask.status == TaskStatus.COMPLETED:
                continue

            while job.status == TaskStatus.PAUSED:
                self._save_job(job)
                time.sleep(0.5)
                job = self.active_jobs[job_id]

            job.current_step = i + 1

            print(f"\n📍 Step {job.current_step}/{job.total_steps}: {subtask.description}")

            # EXECUTE
            subtask.status = TaskStatus.RUNNING
            subtask.started_at = datetime.now().isoformat()
            self._save_job(job)

            success = False
            while subtask.retry_count < self.max_retries and not success:
                try:
                    result = executor(subtask)

                    # EVALUATE
                    if self._evaluate_result(result):
                        subtask.result = result
                        subtask.error = None
                        subtask.status = TaskStatus.COMPLETED
                        subtask.completed_at = datetime.now().isoformat()
                        success = True
                        print(f"   ✅ Completed: {result[:100]}...")
                    else:
                        raise Exception("Result evaluation failed")

                except Exception as e:
                    subtask.retry_count += 1
                    subtask.error = str(e)
                    print(f"   ⚠️ Retry {subtask.retry_count}/{self.max_retries}: {e}")
                    time.sleep(2)

            if not success:
                subtask.status = TaskStatus.FAILED
                job.status = TaskStatus.FAILED
                self._save_job(job)
                print(f"   ❌ Failed after {self.max_retries} retries")
                return

            # RECURSIVE SUMMARIZATION (every N steps)
            if (i + 1) % self.summary_interval == 0:
                self._create_recursive_summary(job)

            self._save_job(job)

        # FINAL SUMMARIZATION
        job.status = TaskStatus.COMPLETED
        job.completed_at = datetime.now().isoformat()
        job.final_result = self._compile_final_result(job)
        job.summary = self._create_final_summary(job)
        self._save_job(job)

        print(f"\n{'='*60}")
        print(f"🎉 JOB COMPLETED: {job.job_id}")
        print(f"{'='*60}\n")

    def _evaluate_result(self, result: str) -> bool:
        """
        Evaluate if a subtask result is valid
        Override this for custom evaluation logic
        """
        return result is not None and len(result) > 0

    def _create_recursive_summary(self, job: AgenticJob):
        """
        Create recursive summary to prevent context drift
        Summarizes last N completed steps
        """
        completed = [st for st in job.subtasks if st.status == TaskStatus.COMPLETED]
        recent = completed[-self.summary_interval:]

        summary_parts = []
        for st in recent:
            summary_parts.append(f"- {st.description}: {st.result[:100] if st.result else 'N/A'}...")

        summary = f"\n📝 RECURSIVE SUMMARY (Steps {job.current_step - len(recent) + 1}-{job.current_step}):\n"
        summary += "\n".join(summary_parts)

        job.summary = summary
        print(summary)

    def _compile_final_result(self, job: AgenticJob) -> str:
        """Compile all subtask results into final output"""
        results = []
        for st in job.subtasks:
            if st.status == TaskStatus.COMPLETED:
                results.append(f"[{st.description}]\n{st.result}\n")

        return "\n".join(results)

    def _create_final_summary(self, job: AgenticJob) -> str:
        """Create final summary of entire job"""
        completed = sum(1 for st in job.subtasks if st.status == TaskStatus.COMPLETED)
        failed = sum(1 for st in job.subtasks if st.status == TaskStatus.FAILED)

        duration = "N/A"
        if job.started_at and job.completed_at:
            start = datetime.fromisoformat(job.started_at)
            end = datetime.fromisoformat(job.completed_at)
            duration = str(end - start)

        return f"""
FINAL SUMMARY - Job {job.job_id}
Task: {job.description}
Status: {job.status.value}
Completed Steps: {completed}/{job.total_steps}
Failed Steps: {failed}
Duration: {duration}
"""

    def get_job_status(self, job_id: str) -> Dict:
        """Get current status of a job"""
        if job_id not in self.active_jobs:
            return {"error": "Job not found"}

        job = self.active_jobs[job_id]
        current_subtask = None
        if 0 < job.current_step <= job.total_steps:
            current_subtask = job.subtasks[job.current_step - 1].description

        return {
            "job_id": job.job_id,
            "description": job.description,
            "status": job.status.value,
            "progress": f"{job.current_step}/{job.total_steps}",
            "current_subtask": current_subtask,
            "summary": job.summary,
            "created_at": job.created_at,
            "started_at": job.started_at,
            "completed_at": job.completed_at
        }

    def get_job_log(self, job_id: str) -> List[Dict]:
        """Get detailed log of all subtasks"""
        if job_id not in self.active_jobs:
            return []

        job = self.active_jobs[job_id]

        return [
            {
                "step": i + 1,
                "description": st.description,
                "status": st.status.value,
                "result": st.result[:200] if st.result else None,
                "error": st.error,
                "retry_count": st.retry_count,
                "started_at": st.started_at,
                "completed_at": st.completed_at
            }
            for i, st in enumerate(job.subtasks)
        ]

    def list_jobs(self) -> List[Dict]:
        """List all jobs"""
        return [
            {
                "job_id": job.job_id,
                "description": job.description,
                "status": job.status.value,
                "progress": f"{job.current_step}/{job.total_steps}",
                "created_at": job.created_at
            }
            for job in self.active_jobs.values()
        ]

    def pause_job(self, job_id: str):
        """Pause a running job"""
        if job_id in self.active_jobs:
            job = self.active_jobs[job_id]
            if job.status not in {TaskStatus.COMPLETED, TaskStatus.FAILED}:
                job.status = TaskStatus.PAUSED
                self._save_job(job)
                print(f"⏸️ Paused job {job_id}")

    def resume_job(self, job_id: str, executor: Callable[[SubTask], str]):
        """Resume a paused job"""
        if job_id in self.active_jobs:
            job = self.active_jobs[job_id]
            if job.status == TaskStatus.PAUSED:
                job.status = TaskStatus.PENDING
                self._save_job(job)
                self.execute_job_async(job_id, executor)
                print(f"▶️ Resumed job {job_id}")

# Global instance
agentic_controller = AgenticLoopController()

# Made with Bob
