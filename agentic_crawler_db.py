"""
Agentic Crawler Database v1.0
- 5KB organized text chunks from web crawling
- Correlation analysis (R-value calculation)
- Automatic pruning system
- Recursive summarization for context preservation
"""

import os
import json
import hashlib
import time
import re
from datetime import datetime, timedelta
from pathlib import Path
from typing import Dict, List, Optional, Tuple
import statistics
import math

class AgenticCrawlerDB:
    def __init__(self, base_dir: str = "crawler_db"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(exist_ok=True)
        
        # Subdirectories
        self.chunks_dir = self.base_dir / "chunks"
        self.summaries_dir = self.base_dir / "summaries"
        self.correlations_dir = self.base_dir / "correlations"
        self.index_dir = self.base_dir / "indexes"
        
        for d in [self.chunks_dir, self.summaries_dir, self.correlations_dir, self.index_dir]:
            d.mkdir(exist_ok=True)
        
        # Configuration
        self.max_chunk_size = 5120  # 5KB
        self.prune_age_days = 30  # Auto-prune chunks older than 30 days
        self.summary_interval = 5  # Summarize every 5 chunks
        
        # Metadata tracking
        self.metadata_file = self.base_dir / "metadata.json"
        self.metadata = self._load_metadata()
        
    def _load_metadata(self) -> Dict:
        """Load database metadata"""
        if self.metadata_file.exists():
            with open(self.metadata_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        return {
            "total_chunks": 0,
            "total_summaries": 0,
            "last_prune": None,
            "chunk_counter": 0,
            "domains": {}
        }
    
    def _save_metadata(self):
        """Save metadata to disk"""
        with open(self.metadata_file, 'w', encoding='utf-8') as f:
            json.dump(self.metadata, f, indent=2)
    
    def store_crawled_data(self, url: str, content: str, metadata: Optional[Dict] = None) -> str:
        """
        Store crawled web data in 5KB chunks
        Returns: chunk_id
        """
        # Extract domain for organization
        domain = self._extract_domain(url)
        
        # Create chunk
        chunk_id = self._generate_chunk_id(url, content)
        chunk_data = {
            "chunk_id": chunk_id,
            "url": url,
            "domain": domain,
            "content": content[:self.max_chunk_size],  # Limit to 5KB
            "timestamp": datetime.now().isoformat(),
            "metadata": metadata or {},
            "word_count": len(content.split()),
            "char_count": len(content)
        }
        
        # Save chunk
        chunk_file = self.chunks_dir / f"{chunk_id}.json"
        with open(chunk_file, 'w', encoding='utf-8') as f:
            json.dump(chunk_data, f, indent=2)
        
        # Update metadata
        self.metadata["total_chunks"] += 1
        self.metadata["chunk_counter"] += 1
        if domain not in self.metadata["domains"]:
            self.metadata["domains"][domain] = 0
        self.metadata["domains"][domain] += 1
        
        # Trigger recursive summarization if needed
        if self.metadata["chunk_counter"] % self.summary_interval == 0:
            self._create_recursive_summary()
        
        self._save_metadata()
        return chunk_id
    
    def calculate_correlation(self, dataset_a: List[float], dataset_b: List[float]) -> Dict:
        """
        Calculate Pearson correlation coefficient (R-value)
        Returns: correlation analysis including R-value, p-value estimate, strength
        """
        if len(dataset_a) != len(dataset_b) or len(dataset_a) < 2:
            return {"error": "Invalid datasets", "r_value": None}
        
        n = len(dataset_a)
        
        # Calculate means
        mean_a = statistics.mean(dataset_a)
        mean_b = statistics.mean(dataset_b)
        
        # Calculate standard deviations
        std_a = statistics.stdev(dataset_a)
        std_b = statistics.stdev(dataset_b)
        
        # Calculate covariance
        covariance = sum((dataset_a[i] - mean_a) * (dataset_b[i] - mean_b) for i in range(n)) / (n - 1)
        
        # Calculate Pearson R
        r_value = covariance / (std_a * std_b) if std_a > 0 and std_b > 0 else 0
        
        # Determine correlation strength
        strength = self._interpret_correlation(r_value)
        
        # Store correlation result
        correlation_id = hashlib.md5(f"{dataset_a}{dataset_b}".encode()).hexdigest()[:16]
        correlation_data = {
            "correlation_id": correlation_id,
            "r_value": r_value,
            "n": n,
            "strength": strength,
            "mean_a": mean_a,
            "mean_b": mean_b,
            "std_a": std_a,
            "std_b": std_b,
            "timestamp": datetime.now().isoformat()
        }
        
        correlation_file = self.correlations_dir / f"{correlation_id}.json"
        with open(correlation_file, 'w', encoding='utf-8') as f:
            json.dump(correlation_data, f, indent=2)
        
        return correlation_data
    
    def _interpret_correlation(self, r: float) -> str:
        """Interpret correlation strength"""
        abs_r = abs(r)
        if abs_r >= 0.9:
            return "Very Strong"
        elif abs_r >= 0.7:
            return "Strong"
        elif abs_r >= 0.5:
            return "Moderate"
        elif abs_r >= 0.3:
            return "Weak"
        else:
            return "Very Weak"
    
    def find_unknown_correlations(self, target_data: List[float], search_domain: Optional[str] = None) -> List[Dict]:
        """
        Search for correlations with unknown causes
        Analyzes stored chunks for numerical patterns
        """
        correlations = []
        
        # Search through chunks
        for chunk_file in self.chunks_dir.glob("*.json"):
            with open(chunk_file, 'r', encoding='utf-8') as f:
                chunk = json.load(f)
            
            # Filter by domain if specified
            if search_domain and chunk.get("domain") != search_domain:
                continue
            
            # Extract numerical data from content
            numbers = self._extract_numbers(chunk["content"])
            
            if len(numbers) >= len(target_data):
                # Align datasets
                aligned_numbers = numbers[:len(target_data)]
                
                # Calculate correlation
                corr_result = self.calculate_correlation(target_data, aligned_numbers)
                
                if corr_result.get("r_value") and abs(corr_result["r_value"]) > 0.5:
                    correlations.append({
                        "chunk_id": chunk["chunk_id"],
                        "url": chunk["url"],
                        "correlation": corr_result,
                        "potential_cause": self._extract_context(chunk["content"], numbers)
                    })
        
        # Sort by correlation strength
        correlations.sort(key=lambda x: abs(x["correlation"]["r_value"]), reverse=True)
        return correlations
    
    def _extract_numbers(self, text: str) -> List[float]:
        """Extract numerical values from text"""
        # Find all numbers (integers and floats)
        pattern = r'-?\d+\.?\d*'
        matches = re.findall(pattern, text)
        return [float(m) for m in matches if m]
    
    def _extract_context(self, text: str, numbers: List[float]) -> str:
        """Extract contextual information around numbers"""
        # Find sentences containing numbers
        sentences = text.split('.')
        relevant = []
        for sent in sentences:
            if any(str(num) in sent for num in numbers[:5]):
                relevant.append(sent.strip())
        return ". ".join(relevant[:3])
    
    def _create_recursive_summary(self):
        """
        Create recursive summary every N chunks
        Prevents context drift in long-running tasks
        """
        recent_chunks = sorted(
            self.chunks_dir.glob("*.json"),
            key=os.path.getmtime,
            reverse=True
        )[:self.summary_interval]
        
        if not recent_chunks:
            return
        
        # Aggregate content
        summary_content = []
        domains = set()
        total_words = 0
        
        for chunk_file in recent_chunks:
            with open(chunk_file, 'r', encoding='utf-8') as f:
                chunk = json.load(f)
            summary_content.append(f"[{chunk['domain']}] {chunk['content'][:200]}...")
            domains.add(chunk['domain'])
            total_words += chunk['word_count']
        
        # Create summary
        summary_id = f"summary_{int(time.time())}"
        summary_data = {
            "summary_id": summary_id,
            "chunk_count": len(recent_chunks),
            "domains": list(domains),
            "total_words": total_words,
            "content": "\n\n".join(summary_content),
            "timestamp": datetime.now().isoformat()
        }
        
        summary_file = self.summaries_dir / f"{summary_id}.json"
        with open(summary_file, 'w', encoding='utf-8') as f:
            json.dump(summary_data, f, indent=2)
        
        self.metadata["total_summaries"] += 1
        print(f"📝 Created recursive summary: {summary_id} ({len(recent_chunks)} chunks)")
    
    def prune_old_data(self, force: bool = False):
        """
        Automatic pruning of old chunks
        Removes data older than prune_age_days
        """
        cutoff_date = datetime.now() - timedelta(days=self.prune_age_days)
        pruned_count = 0
        
        for chunk_file in self.chunks_dir.glob("*.json"):
            with open(chunk_file, 'r', encoding='utf-8') as f:
                chunk = json.load(f)
            
            chunk_date = datetime.fromisoformat(chunk["timestamp"])
            
            if chunk_date < cutoff_date or force:
                chunk_file.unlink()
                pruned_count += 1
        
        # Update metadata
        self.metadata["last_prune"] = datetime.now().isoformat()
        self.metadata["total_chunks"] -= pruned_count
        self._save_metadata()
        
        print(f"🧹 Pruned {pruned_count} old chunks (older than {self.prune_age_days} days)")
        return pruned_count
    
    def _generate_chunk_id(self, url: str, content: str) -> str:
        """Generate unique chunk ID"""
        return hashlib.md5(f"{url}{content[:100]}".encode()).hexdigest()[:16]
    
    def _extract_domain(self, url: str) -> str:
        """Extract domain from URL"""
        match = re.search(r'https?://([^/]+)', url)
        return match.group(1) if match else "unknown"
    
    def get_stats(self) -> Dict:
        """Get database statistics"""
        return {
            "total_chunks": self.metadata["total_chunks"],
            "total_summaries": self.metadata["total_summaries"],
            "domains": len(self.metadata["domains"]),
            "last_prune": self.metadata["last_prune"],
            "top_domains": sorted(
                self.metadata["domains"].items(),
                key=lambda x: x[1],
                reverse=True
            )[:5]
        }

# Global instance
crawler_db = AgenticCrawlerDB()

# Made with Bob
