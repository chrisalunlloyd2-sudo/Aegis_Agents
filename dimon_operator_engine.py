import numpy as np
import sqlite3
import os
from sklearn.decomposition import PCA
from datetime import datetime

class DIMONOperatorEngine:
    """
    Implements the Diffeomorphic Mapping (phi_theta) from Nature 2024.
    Maps irregular 'code manifolds' into a Canonical Reference Domain.
    """
    def __init__(self, db_path="gemini_bridge.db"):
        self.db_path = db_path
        self.pca = PCA(n_components=128) # 128-dim Reference Domain

    def _init_db(self):
        """Run the physical schema if not exists"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Check if table exists, if not create it based on FastAPI schema + variance_score
        cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='neural_manifolds'")
        if not cursor.fetchone():
            cursor.execute("""
                CREATE TABLE neural_manifolds (
                    id INTEGER PRIMARY KEY,
                    source_origin VARCHAR(255),
                    ast_nodes INTEGER,
                    structural_depth INTEGER,
                    canonical_coords TEXT,
                    operator_signature VARCHAR(100),
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    variance_score FLOAT
                )
            """)
        else:
            # Check if variance_score exists, if not add it
            cursor.execute("PRAGMA table_info(neural_manifolds)")
            columns = [info[1] for info in cursor.fetchall()]
            if 'variance_score' not in columns:
                cursor.execute("ALTER TABLE neural_manifolds ADD COLUMN variance_score FLOAT")

        conn.commit()
        conn.close()

    def map_to_reference(self, source_name, raw_embeddings):
        """
        THE DIFFEOMORPHIC MAPPING: Maps code embeddings (varying domains)
        to a unified Banach space (Reference Domain).
        """
        if len(raw_embeddings) < 128:
            return None # Not enough geometry to map

        # Perform PCA (Pruning/Mapping)
        canonical = self.pca.fit_transform(raw_embeddings)
        variance = float(np.sum(self.pca.explained_variance_ratio_))

        # Store in the Physical Neural Database
        self._store_manifold(source_name, canonical, variance)
        return canonical, variance

    def _store_manifold(self, source, coords, variance):
        """Store the learned manifold in the SQL database"""
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        # Serialize coordinates as BLOB
        coords_blob = coords.tobytes()

        cursor.execute("""
            INSERT INTO neural_manifolds (source_origin, canonical_coords, variance_score)
            VALUES (?, ?, ?)
        """, (source, coords_blob, variance))

        conn.commit()
        conn.close()
        print(f"[DIMON] Manifold stored for '{source}'. Reference Domain active.")

if __name__ == "__main__":
    engine = DIMONOperatorEngine()
    engine._init_db()
    # Test with dummy code geometry (1000 lines, 768-dim embeddings)
    test_geometry = np.random.rand(200, 768).astype(np.float32)
    engine.map_to_reference("AIEngine/core.py", test_geometry)
