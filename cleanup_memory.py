"""
AEGIS Memory Cleanup Utility
Cleans up bloated indexes and removes old memory files
"""

from timescale_memory import memory
from pathlib import Path
import json

def cleanup_bloated_index():
    """Clean up the old bloated global_index.json"""
    old_index = memory.base_path / "global_index.json"
    if old_index.exists():
        print(f"[CLEANUP] Removing old bloated index: {old_index}")
        old_index.unlink()
        print("✅ Old index removed")

def cleanup_old_indexes():
    """Remove old index segments, keep only last 10"""
    memory.cleanup_old_indexes(keep_segments=10)
    print("✅ Old index segments cleaned")

def show_index_stats():
    """Show current index statistics"""
    indexes_dir = memory.base_path / "indexes"
    if indexes_dir.exists():
        index_files = list(indexes_dir.glob("index_segment_*.json"))
        print(f"\n📊 Index Statistics:")
        print(f"   Total segments: {len(index_files)}")

        total_size = 0
        for idx_file in index_files:
            size = idx_file.stat().st_size
            total_size += size
            print(f"   - {idx_file.name}: {size/1024:.1f} KB")

        print(f"   Total size: {total_size/1024:.1f} KB")

        if total_size > 100 * 1024:
            print("   ⚠️ WARNING: Indexes are large, consider cleanup")
        else:
            print("   ✅ Index size is healthy")

def rebuild_indexes():
    """Rebuild indexes from scratch (nuclear option)"""
    print("[REBUILD] Rebuilding all indexes from memory files...")

    # Remove all old indexes
    indexes_dir = memory.base_path / "indexes"
    if indexes_dir.exists():
        for idx_file in indexes_dir.glob("index_segment_*.json"):
            idx_file.unlink()

    # Reset memory system
    memory.current_index_segment = 0
    memory.index = {"sessions": {}, "subjects": {}, "keywords": {}, "file_count": 0}
    memory.seen_hashes.clear()

    # Scan all memory files and rebuild
    file_count = 0
    for session_dir in memory.base_path.glob("*/"):
        if session_dir.name in ["secrets", "weekly_summaries", "feelings", "indexes"]:
            continue

        session_id = session_dir.name
        for subject_dir in session_dir.glob("*/"):
            subject = subject_dir.name
            for date_dir in subject_dir.glob("*/"):
                for hour_dir in date_dir.glob("*/"):
                    for mem_file in hour_dir.glob("*.txt"):
                        try:
                            with open(mem_file, 'r', encoding='utf-8') as f:
                                content = f.read()
                                memory._update_index(session_id, subject, str(mem_file), content)
                                file_count += 1
                        except Exception:
                            pass

    print(f"✅ Rebuilt indexes from {file_count} memory files")

if __name__ == "__main__":
    print("🧹 AEGIS Memory Cleanup Utility")
    print("=" * 50)

    # Show current stats
    show_index_stats()

    print("\n🧹 Cleaning up...")

    # Clean up old bloated index
    cleanup_bloated_index()

    # Clean up old segments
    cleanup_old_indexes()

    print("\n📊 After cleanup:")
    show_index_stats()

    print("\n✅ Cleanup complete!")
    print("\nTo rebuild indexes from scratch, run:")
    print("  python cleanup_memory.py --rebuild")

# Made with Bob
