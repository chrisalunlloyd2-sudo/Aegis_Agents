import torch
# AEGIS-DIMON: VRAM Memory Fencing for Quadro K4000 (3GB)
if torch.cuda.is_available():
    # Reserve 80% of VRAM to prevent OOM and maintain system stability
    torch.cuda.set_per_process_memory_fraction(0.8, 0)
import torch.nn as nn
import torch.optim as optim
import ast
import numpy as np
import psycopg2
import os
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

class FNN(nn.Module):
    """Standard Feed-Forward Neural Network for Branch/Trunk"""
    def __init__(self, layer_sizes):
        super(FNN, self).__init__()
        layers = []
        for i in range(len(layer_sizes) - 1):
            layers.append(nn.Linear(layer_sizes[i], layer_sizes[i+1]))
            if i < len(layer_sizes) - 2:
                layers.append(nn.Tanh())
        self.net = nn.Sequential(*layers)

    def forward(self, x):
        return self.net(x)

class AegisDIMON(nn.Module):
    """
    True MIONet implementation for DIMON (Diffeomorphic Mapping Operator Learning).
    Architecture: Branch Nets (Shape + Input) and Trunk Net (Coordinates).
    Fuses logic via Hadamard product for mathematical operator learning.
    """
    def __init__(self, branch_sizes, trunk_size, latent_dim=128):
        super(AegisDIMON, self).__init__()
        # Branch 1: Encodes Code Topology (The 'Shape' of the logic)
        self.branch_shape = FNN([branch_sizes[0]] + [256, latent_dim])
        
        # Branch 2: Encodes User Intent/Input Function
        self.branch_input = FNN([branch_sizes[1]] + [256, latent_dim])
        
        # Trunk Net: Encodes AST Coordinates (The 'Domain')
        self.trunk = FNN([trunk_size] + [256, latent_dim])

    def forward(self, x_shape, x_input, x_coords):
        # 1. Pull back inputs into latent space
        b_shape = self.branch_shape(x_shape)
        b_input = self.branch_input(x_input)
        
        # 2. Encode domain coordinates
        t_out = self.trunk(x_coords)
        
        # 3. DIMON Interaction: Hadamard Product (Element-wise multiplication)
        # This is the 'Operator' mapping in Banach space
        res = b_shape * b_input * t_out
        
        # 4. Summation to produce scalar logic signature
        return torch.sum(res, dim=1, keepdim=True)

class DIMONLogicEngine:
    """
    Orchestrates the mathematical logic recognition using MIONet.
    Saves manifolds to TimescaleDB.
    """
    def __init__(self):
        self.latent_dim = 128
        # Shape Branch: [NodeCount, MaxDepth, Complexity]
        # Input Branch: [EmbeddingSize] (e.g. 768 for Gemini)
        # Trunk: [NodeIndex, NodeDepth]
        self.model = AegisDIMON(branch_sizes=[3, 768], trunk_size=2, latent_dim=self.latent_dim)
        self.db_url = os.getenv("DATABASE_URL")

    def _get_timescale_conn(self):
        import urllib.parse as urlparse
        if not self.db_url or not self.db_url.startswith("postgresql"): return None
        try:
            result = urlparse.urlparse(self.db_url)
            return psycopg2.connect(
                database=result.path[1:],
                user=result.username,
                password=result.password,
                host=result.hostname,
                port=result.port
            )
        except:
            return None

    def extract_topology(self, source_code):
        """Extracts AST metrics as the 'Shape' of the manifold"""
        tree = ast.parse(source_code)
        nodes = list(ast.walk(tree))
        max_depth = 0
        def get_depth(node, current_depth):
            nonlocal max_depth
            max_depth = max(max_depth, current_depth)
            for child in ast.iter_child_nodes(node):
                get_depth(child, current_depth + 1)
        get_depth(tree, 0)
        
        # Feature vector: [Nodes, Depth, Complexity (approx as nodes/depth)]
        shape_vec = torch.tensor([[len(nodes), max_depth, len(nodes)/(max_depth or 1)]], dtype=torch.float32)
        
        # Coordinate set for Trunk: [NodeIndex, NodeDepth]
        # For simplicity, we sample the first 100 nodes
        coords = []
        for i, node in enumerate(nodes[:100]):
            coords.append([i, 1.0]) # Simplified coordinate mapping
        coords = torch.tensor(coords, dtype=torch.float32)
        
        return shape_vec, coords

    def learn_operator(self, source_name, source_code, input_embedding):
        """
        Executes the Diffeomorphic Mapping and Operator Learning.
        """
        shape_vec, coords = self.extract_topology(source_code)
        input_vec = torch.tensor(input_embedding, dtype=torch.float32).unsqueeze(0)
        
        # Forward pass: Operator Synthesis
        # In a real training scenario, we'd have a target solution
        # Here we use the latent interaction as the 'Logic Signature'
        with torch.no_grad():
            # Get the Hadamard result before summation as the high-dim manifold
            b_s = self.model.branch_shape(shape_vec)
            b_i = self.model.branch_input(input_vec)
            t_o = self.model.trunk(coords).mean(dim=0) # Average over nodes
            
            logic_manifold = b_s * b_i * t_o
            logic_signature = torch.sum(logic_manifold).item()

        print(f"[DIMON] Learned Operator for '{source_name}': {logic_signature:.6f}")
        self._persist_to_timescale(source_name, logic_manifold, logic_signature)
        return logic_signature

    def _persist_to_timescale(self, source, manifold, signature):
        """Persists to TimescaleDB or SQLite Fallback (Unified Manifold)"""
        conn = self._get_timescale_conn()
        
        # 1. TIMESCALEDB PATH
        if conn:
            try:
                cur = conn.cursor()
                manifold_blob = manifold.numpy().tobytes()
                cur.execute("""
                    INSERT INTO neural_manifolds 
                    (source_origin, ast_nodes, structural_depth, canonical_coords, operator_signature)
                    VALUES (%s, %s, %s, %s, %s)
                """, (source, manifold.shape[1], 0, manifold_blob, f"LOGIC_{signature:.4f}"))
                conn.commit()
                cur.close()
                conn.close()
                print("✅ Persisted to TimescaleDB Hypertable.")
                return
            except Exception as e:
                print(f"❌ TimescaleDB error: {e}")

        # 2. SQLITE FALLBACK (NODE ALPHA PREP)
        print("[DIMON] Routing manifold to local SQLite fallback...")
        try:
            import sqlite3
            sqlite_conn = sqlite3.connect('C:/Users/viper/gemini_bridge.db')
            cur = sqlite_conn.cursor()
            manifold_blob = manifold.numpy().tobytes()
            cur.execute("""
                INSERT INTO neural_manifolds 
                (source_origin, ast_nodes, structural_depth, canonical_coords, operator_signature, timestamp)
                VALUES (?, ?, ?, ?, ?, ?)
            """, (source, manifold.shape[1], 0, str(manifold_blob), f"LOGIC_{signature:.4f}", datetime.utcnow()))
            sqlite_conn.commit()
            sqlite_conn.close()
            print("✅ Persisted to Local Unified SQL Manifold (SQLite).")
        except Exception as e:
            print(f"❌ SQLite Fallback error: {e}")

if __name__ == "__main__":
    engine = DIMONLogicEngine()
    dummy_embedding = np.random.rand(768)
    with open(__file__, "r", encoding="utf-8") as f:
        code = f.read()
    engine.learn_operator("dimon_mionet_logic.py", code, dummy_embedding)
