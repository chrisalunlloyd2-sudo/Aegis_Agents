"""
Agentic Crawler Database v2.0
- Human-readable 5KB text chunks from web crawling
- Query-based web search and page crawling
- Boolean search with per-interaction NOT tables
- Correlation analysis (R-value calculation)
- Automatic pruning for expired and unused data
"""

import hashlib
import json
import math
import os
import re
import statistics
import time
from collections import deque
from datetime import datetime, timedelta
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, quote_plus, unquote, urljoin, urlparse
from urllib.request import Request, urlopen


class _HTMLContentExtractor(HTMLParser):
    """Extract visible text and links without extra dependencies."""

    def __init__(self):
        super().__init__()
        self.links: List[str] = []
        self.title = ""
        self._text_parts: List[str] = []
        self._skip_depth = 0
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        attrs_map = dict(attrs)

        if tag in {"script", "style", "noscript"}:
            self._skip_depth += 1
            return

        if tag == "title":
            self._in_title = True

        if tag == "a" and attrs_map.get("href"):
            self.links.append(attrs_map["href"])

        if tag in {"p", "div", "section", "article", "li", "br", "h1", "h2", "h3", "h4"}:
            self._text_parts.append("\n")

    def handle_endtag(self, tag):
        if tag in {"script", "style", "noscript"} and self._skip_depth:
            self._skip_depth -= 1
            return

        if tag == "title":
            self._in_title = False

        if tag in {"p", "div", "section", "article", "li", "br", "h1", "h2", "h3", "h4"}:
            self._text_parts.append("\n")

    def handle_data(self, data):
        if self._skip_depth:
            return

        cleaned = " ".join(data.split())
        if not cleaned:
            return

        if self._in_title and not self.title:
            self.title = cleaned

        self._text_parts.append(cleaned + " ")

    def get_text(self) -> str:
        text = unescape("".join(self._text_parts))
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text.strip()

class AgenticCrawlerDB:
    def __init__(self, base_dir: str = "crawler_db"):
        self.base_dir = Path(base_dir)
        self.base_dir.mkdir(exist_ok=True)
        
        # Subdirectories
        self.chunks_dir = self.base_dir / "chunks"
        self.summaries_dir = self.base_dir / "summaries"
        self.correlations_dir = self.base_dir / "correlations"
        self.index_dir = self.base_dir / "indexes"
        self.reports_dir = self.base_dir / "reports"
        self.not_tables_dir = self.index_dir / "not_tables"
        
        for d in [
            self.chunks_dir,
            self.summaries_dir,
            self.correlations_dir,
            self.index_dir,
            self.reports_dir,
            self.not_tables_dir,
        ]:
            d.mkdir(exist_ok=True)
        
        # Configuration
        self.max_chunk_size = 5120  # 5KB
        self.prune_age_days = 30  # Auto-prune chunks older than 30 days
        self.prune_unused_days = 14
        self.summary_interval = 5  # Summarize every 5 chunks
        self.user_agent = "Mozilla/5.0 (compatible; AEGIS/2.0; +https://localhost)"
        
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
    
    def _normalize_url(self, url: str) -> str:
        parsed = urlparse(url.strip())
        if parsed.scheme not in {"http", "https"}:
            return ""
        normalized = parsed._replace(fragment="")
        return normalized.geturl()
    
    def _extract_domain(self, url: str) -> str:
        try:
            return urlparse(url).netloc or "unknown"
        except Exception:
            return "unknown"
    
    def _split_content(self, content: str) -> List[str]:
        """Split a document into readable 5KB chunks."""
        cleaned = re.sub(r"\s+\n", "\n", content)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()
        if not cleaned:
            return []
        
        paragraphs = [part.strip() for part in re.split(r"\n{2,}", cleaned) if part.strip()]
        segments: List[str] = []
        current = ""
        
        for paragraph in paragraphs:
            candidate = f"{current}\n\n{paragraph}".strip() if current else paragraph
            if len(candidate.encode("utf-8")) <= self.max_chunk_size:
                current = candidate
                continue
            
            if current:
                segments.append(current)
                current = ""
            
            remaining = paragraph
            while len(remaining.encode("utf-8")) > self.max_chunk_size:
                slice_size = self.max_chunk_size - 64
                segments.append(remaining[:slice_size].strip())
                remaining = remaining[slice_size:].strip()
            current = remaining
        
        if current:
            segments.append(current)
        
        return segments
    
    def _clean_search_result_url(self, href: str) -> str:
        href = unescape(href.strip())
        if href.startswith("//"):
            href = "https:" + href
        
        if "duckduckgo.com/l/?" in href:
            query = parse_qs(urlparse(href).query)
            target = query.get("uddg", [""])[0]
            return unquote(target)
        
        return href
    
    def _strip_html(self, value: str) -> str:
        return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", unescape(value))).strip()
    
    def _fetch_text_resource(self, url: str, timeout: int = 15) -> Dict:
        request = Request(url, headers={"User-Agent": self.user_agent})
        with urlopen(request, timeout=timeout) as response:
            raw = response.read(262144)
            content_type = response.headers.get("Content-Type", "")
            charset = response.headers.get_content_charset() or "utf-8"
            payload = raw.decode(charset, errors="replace")
            return {
                "url": response.geturl(),
                "content_type": content_type,
                "payload": payload,
            }
    
    def _fetch_page(self, url: str, timeout: int = 15) -> Dict:
        fetched = self._fetch_text_resource(url, timeout=timeout)
        content_type = fetched["content_type"].lower()
        payload = fetched["payload"]
        
        if "html" in content_type:
            parser = _HTMLContentExtractor()
            parser.feed(payload)
            text = parser.get_text()
            links = [urljoin(fetched["url"], link) for link in parser.links]
            return {
                "url": fetched["url"],
                "title": parser.title or fetched["url"],
                "text": text,
                "links": links,
                "content_type": content_type,
            }
        
        if "text/plain" in content_type or fetched["url"].endswith(".txt"):
            return {
                "url": fetched["url"],
                "title": fetched["url"],
                "text": payload,
                "links": [],
                "content_type": content_type,
            }
        
        raise ValueError(f"Unsupported content type for crawl: {content_type or 'unknown'}")
    
    def store_text_chunks(
        self,
        url: str,
        content: str,
        metadata: Optional[Dict] = None,
        ttl_hours: Optional[int] = None,
    ) -> List[str]:
        """Store a document as one or more human-readable 5KB chunks."""
        normalized_url = self._normalize_url(url) or url
        domain = self._extract_domain(normalized_url)
        segments = self._split_content(content)
        if not segments:
            return []
        
        timestamp = datetime.now().isoformat()
        expires_at = None
        if ttl_hours is not None:
            expires_at = (datetime.now() + timedelta(hours=ttl_hours)).isoformat()
        
        document_id = hashlib.md5(normalized_url.encode("utf-8")).hexdigest()[:16]
        shared_metadata = dict(metadata or {})
        shared_metadata.setdefault("document_id", document_id)
        chunk_ids: List[str] = []
        
        for index, segment in enumerate(segments, start=1):
            chunk_id = self._generate_chunk_id(normalized_url, segment, index)
            chunk_data = {
                "chunk_id": chunk_id,
                "document_id": document_id,
                "url": normalized_url,
                "domain": domain,
                "title": shared_metadata.get("title"),
                "content": segment,
                "timestamp": timestamp,
                "expires_at": expires_at,
                "metadata": {
                    **shared_metadata,
                    "segment_index": index,
                    "segment_count": len(segments),
                },
                "word_count": len(segment.split()),
                "char_count": len(segment),
                "access_count": 0,
                "last_accessed": None,
            }
            
            chunk_file = self.chunks_dir / f"{chunk_id}.json"
            with open(chunk_file, 'w', encoding='utf-8') as f:
                json.dump(chunk_data, f, indent=2)
            
            self.metadata["total_chunks"] += 1
            self.metadata["chunk_counter"] += 1
            self.metadata["domains"][domain] = self.metadata["domains"].get(domain, 0) + 1
            chunk_ids.append(chunk_id)
            
            if self.metadata["chunk_counter"] % self.summary_interval == 0:
                self._create_recursive_summary()
        
        self._save_metadata()
        return chunk_ids
    
    def store_crawled_data(
        self,
        url: str,
        content: str,
        metadata: Optional[Dict] = None,
        ttl_hours: Optional[int] = None,
    ) -> str:
        """Backwards-compatible storage entrypoint that returns the first chunk ID."""
        chunk_ids = self.store_text_chunks(url, content, metadata=metadata, ttl_hours=ttl_hours)
        return chunk_ids[0] if chunk_ids else ""
    
    def search_web(self, query: str, max_results: int = 5, timeout: int = 15) -> List[Dict]:
        """Perform a lightweight web search using DuckDuckGo HTML results."""
        if not query.strip():
            return []
        
        if query.strip().startswith(("http://", "https://")):
            normalized = self._normalize_url(query)
            return [{"title": normalized, "url": normalized, "source": "direct"}] if normalized else []
        
        search_url = f"https://duckduckgo.com/html/?q={quote_plus(query)}"
        try:
            fetched = self._fetch_text_resource(search_url, timeout=timeout)
        except (HTTPError, URLError, TimeoutError, ValueError) as exc:
            return [{"title": "search_error", "url": "", "snippet": str(exc), "source": "duckduckgo"}]
        
        html = fetched["payload"]
        matches = re.findall(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', html, flags=re.IGNORECASE | re.DOTALL)
        
        results: List[Dict] = []
        seen = set()
        for href, raw_title in matches:
            cleaned_url = self._clean_search_result_url(href)
            normalized_url = self._normalize_url(cleaned_url)
            if not normalized_url:
                continue
            if "duckduckgo.com" in self._extract_domain(normalized_url):
                continue
            if normalized_url in seen:
                continue
            
            seen.add(normalized_url)
            results.append(
                {
                    "title": self._strip_html(raw_title) or normalized_url,
                    "url": normalized_url,
                    "domain": self._extract_domain(normalized_url),
                    "source": "duckduckgo",
                }
            )
            if len(results) >= max_results:
                break
        
        return results
    
    def crawl_url(
        self,
        url: str,
        max_depth: int = 0,
        max_pages: int = 3,
        same_domain_only: bool = True,
        metadata: Optional[Dict] = None,
        ttl_hours: Optional[int] = 24 * 7,
    ) -> Dict:
        """Crawl a URL and optionally follow same-domain links."""
        normalized_start = self._normalize_url(url)
        if not normalized_start:
            return {"error": f"Invalid URL: {url}", "pages_crawled": 0, "stored_chunks": []}
        
        start_domain = self._extract_domain(normalized_start)
        queue = deque([(normalized_start, 0)])
        visited = set()
        stored_chunks: List[Dict] = []
        errors: List[str] = []
        
        while queue and len(visited) < max_pages:
            current_url, depth = queue.popleft()
            if current_url in visited:
                continue
            visited.add(current_url)
            
            try:
                page = self._fetch_page(current_url)
            except Exception as exc:
                errors.append(f"{current_url}: {exc}")
                continue
            
            page_metadata = dict(metadata or {})
            page_metadata.update(
                {
                    "title": page.get("title"),
                    "crawl_depth": depth,
                    "crawl_source": "agentic_crawl",
                }
            )
            chunk_ids = self.store_text_chunks(
                page["url"],
                page["text"],
                metadata=page_metadata,
                ttl_hours=ttl_hours,
            )
            stored_chunks.append(
                {
                    "url": page["url"],
                    "title": page.get("title"),
                    "chunk_ids": chunk_ids,
                    "depth": depth,
                }
            )
            
            if depth >= max_depth:
                continue
            
            for link in page.get("links", []):
                normalized_link = self._normalize_url(link)
                if not normalized_link or normalized_link in visited:
                    continue
                if same_domain_only and self._extract_domain(normalized_link) != start_domain:
                    continue
                queue.append((normalized_link, depth + 1))
        
        self.prune_old_data()
        return {
            "start_url": normalized_start,
            "pages_crawled": len(visited),
            "stored_chunks": stored_chunks,
            "errors": errors,
        }
    
    def research_query(
        self,
        query: str,
        max_results: int = 5,
        max_pages: int = 5,
        same_domain_only: bool = False,
        ttl_hours: Optional[int] = 24 * 7,
    ) -> Dict:
        """Search the web and crawl the top results into the text database."""
        search_results = self.search_web(query, max_results=max_results)
        if search_results and search_results[0].get("title") == "search_error":
            return {"query": query, "search_results": search_results, "crawls": [], "errors": [search_results[0]["snippet"]]}
        
        crawls = []
        errors = []
        pages_per_result = max(1, max_pages // max(1, len(search_results)))
        
        for result in search_results:
            crawl_result = self.crawl_url(
                result["url"],
                max_depth=0,
                max_pages=pages_per_result,
                same_domain_only=same_domain_only,
                metadata={"query": query, "search_title": result.get("title")},
                ttl_hours=ttl_hours,
            )
            crawls.append(crawl_result)
            errors.extend(crawl_result.get("errors", []))
        
        return {
            "query": query,
            "search_results": search_results,
            "crawls": crawls,
            "errors": errors,
        }
    
    def _matches_boolean_query(self, text: str, query: str) -> bool:
        """Evaluate a simple AND/OR/NOT query against text."""
        tokens = re.findall(r'"[^"]+"|\S+', query)
        if not tokens:
            return True
        
        result = None
        pending_operator = "AND"
        negate_next = False
        haystack = text.lower()
        
        for token in tokens:
            upper = token.upper()
            if upper in {"AND", "OR"}:
                pending_operator = upper
                continue
            if upper == "NOT":
                negate_next = not negate_next
                continue
            
            term = token.strip('"').lower()
            term_result = term in haystack
            if negate_next:
                term_result = not term_result
                negate_next = False
            
            if result is None:
                result = term_result
            elif pending_operator == "AND":
                result = result and term_result
            else:
                result = result or term_result
        
        return bool(result)
    
    def _chunk_matches_time_range(self, chunk: Dict, time_range: Optional[str]) -> bool:
        if not time_range:
            return True
        
        timestamp = datetime.fromisoformat(chunk["timestamp"])
        now = datetime.now()
        if time_range == "last_hour":
            cutoff = now - timedelta(hours=1)
        elif time_range == "today":
            cutoff = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif time_range == "last_week":
            cutoff = now - timedelta(days=7)
        elif time_range == "last_month":
            cutoff = now - timedelta(days=30)
        else:
            return True
        
        return timestamp >= cutoff
    
    def _is_expired(self, chunk: Dict) -> bool:
        expires_at = chunk.get("expires_at")
        if not expires_at:
            return False
        try:
            return datetime.now() >= datetime.fromisoformat(expires_at)
        except ValueError:
            return False
    
    def _touch_chunk(self, chunk_path: Path, chunk: Dict):
        chunk["access_count"] = int(chunk.get("access_count", 0)) + 1
        chunk["last_accessed"] = datetime.now().isoformat()
        with open(chunk_path, 'w', encoding='utf-8') as f:
            json.dump(chunk, f, indent=2)
    
    def _write_not_table(self, interaction_id: str, query: str, skipped: List[Dict]) -> str:
        payload = {
            "interaction_id": interaction_id,
            "query": query,
            "generated_at": datetime.now().isoformat(),
            "skipped_chunks": skipped,
        }
        path = self.not_tables_dir / f"not_table_{interaction_id}.json"
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(payload, f, indent=2)
        return str(path)
    
    def search_chunks(
        self,
        query: str,
        domain: Optional[str] = None,
        time_range: Optional[str] = None,
        include_expired: bool = False,
        limit: int = 10,
        interaction_id: Optional[str] = None,
        persist_not_table: bool = False,
    ) -> List[Dict]:
        """Search stored chunks with boolean matching and optional NOT table output."""
        results = []
        skipped: List[Dict] = []
        chunk_files = sorted(self.chunks_dir.glob("*.json"), key=os.path.getmtime, reverse=True)
        
        for chunk_file in chunk_files:
            with open(chunk_file, 'r', encoding='utf-8') as f:
                chunk = json.load(f)
            
            if domain and chunk.get("domain") != domain:
                skipped.append({"chunk_id": chunk["chunk_id"], "reason": "domain_mismatch"})
                continue
            if not include_expired and self._is_expired(chunk):
                skipped.append({"chunk_id": chunk["chunk_id"], "reason": "expired"})
                continue
            if not self._chunk_matches_time_range(chunk, time_range):
                skipped.append({"chunk_id": chunk["chunk_id"], "reason": "time_filter"})
                continue
            
            haystack = " ".join(
                [
                    chunk.get("title") or "",
                    chunk.get("url") or "",
                    chunk.get("content") or "",
                    json.dumps(chunk.get("metadata", {}), ensure_ascii=False),
                ]
            )
            if not self._matches_boolean_query(haystack, query):
                skipped.append({"chunk_id": chunk["chunk_id"], "reason": "boolean_miss"})
                continue
            
            self._touch_chunk(chunk_file, chunk)
            results.append(
                {
                    "chunk_id": chunk["chunk_id"],
                    "url": chunk["url"],
                    "domain": chunk["domain"],
                    "title": chunk.get("title"),
                    "timestamp": chunk["timestamp"],
                    "expires_at": chunk.get("expires_at"),
                    "excerpt": chunk["content"][:280],
                    "metadata": chunk.get("metadata", {}),
                    "access_count": int(chunk.get("access_count", 0)) + 1,
                }
            )
            if len(results) >= limit:
                break
        
        if persist_not_table and interaction_id:
            self._write_not_table(interaction_id, query, skipped)
        
        return results
    
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
