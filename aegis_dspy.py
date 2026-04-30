import dspy
import os
from dotenv import load_dotenv

load_dotenv()

# ==========================================
# 🧠 AEGIS-DSPY: DECLARATIVE LOGIC ENGINE
# Objective: Replace manual prompting with compiled signatures.
# ==========================================

class AegisLogicSignature(dspy.Signature):
    """
    180-IQ Symbolic Mapping.
    Input: A high-level manifold objective or code fragment.
    Output: A 5-Nines optimized logic block and mathematical explanation.
    """
    context = dspy.InputField(desc="The topological state of the current workspace or med list.")
    objective = dspy.InputField(desc="The 180-IQ task requested by the Kernel.")
    optimized_logic = dspy.OutputField(desc="The high-signal code or logical solution.")
    explanation = dspy.OutputField(desc="The mathematical rationale (DIMON rationale).")

class AegisOptimizer(dspy.Module):
    def __init__(self):
        super().__init__()
        # Using ChainOfThought for deep architectural reasoning
        self.generate_logic = dspy.ChainOfThought(AegisLogicSignature)

    def forward(self, context, objective):
        return self.generate_logic(context=context, objective=objective)

def initialize_dspy(model_name="gemini/gemini-1.5-pro"):
    """
    Initializes the DSPy compiler with the Gemini Teacher.
    """
    google_paid_enabled = os.getenv("AEGIS_ENABLE_GOOGLE_PAID", "0").strip().lower() in {"1", "true", "yes", "on"}
    if not google_paid_enabled:
        print("⚠️ [DSPY] Google paid teacher is disabled by policy. Skipping DSPy cloud initialization.")
        return None
    api_key = os.getenv("GEMINI_API_KEY")
    if not api_key:
        print("❌ [DSPY] Missing API Key. Manifold cannot compile.")
        return None
    
    # Configure the LM
    gemini = dspy.Google(model=model_name, api_key=api_key)
    dspy.settings.configure(lm=gemini)
    return AegisOptimizer()

if __name__ == "__main__":
    # Self-Compilation Test
    print("[DSPY] Initializing 180-IQ Signature...")
    optimizer = initialize_dspy()
    if optimizer:
        result = optimizer(
            context="Quadro K4000 (3GB VRAM), Node Alpha Active, FastAPI bridge stable.",
            objective="Implement a PagedAttention scaffold for the distilled core."
        )
        print(f"\n--- OPTIMIZED LOGIC ---\n{result.optimized_logic}")
        print(f"\n--- RATIONALE ---\n{result.explanation}")
