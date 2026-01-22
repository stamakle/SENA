
import sys
import os
from pathlib import Path

# Add project root to sys.path
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from src.graph.state import GraphState
from src.graph.nodes.supervisor import supervisor_node

def test_contextual_lookup():
    print("Testing Supervisor Contextual Lookup Logic...")
    
    # Scene 1: User asks "whats the bdf" with NO live output
    # Expectation: Retrieval (rag) - assuming it doesn't know context
    state_no_context = GraphState(
        query="whats the bdf",
        history=[],
        last_live_output=""
    )
    result = supervisor_node(state_no_context)
    print(f"1. No Context -> Route: {result['route']}")
    
    # Scene 2: User asks "whats the bdf" WITH live output
    # Expectation: Response (response) - skipping retrieval
    state_with_context = GraphState(
        query="whats the bdf",
        history=[],
        last_live_output="01:00.0 processing..."
    )
    result = supervisor_node(state_with_context)
    print(f"2. With Context -> Route: {result['route']}")
    if result['route'] == 'response':
        print("   ✅ SUCCESS: Routed to response for context extraction.")
    else:
        print(f"   ❌ FAILURE: Routed to {result['route']} (Expected 'response')")

    # Scene 3: User asks for SPEC even with context
    # Expectation: Retrieval (rag) or Doc Search
    state_spec = GraphState(
        query="check the spec for bdf format",
        history=[],
        last_live_output="01:00.0"
    )
    result = supervisor_node(state_spec)
    print(f"3. Spec Query -> Route: {result['route']}")
    if result['route'] != 'response':
        print("   ✅ SUCCESS: Correctly routed to retrieval for Spec question.")
    else:
        print("   ❌ FAILURE: Bypassed retrieval for Spec question.")

if __name__ == "__main__":
    test_contextual_lookup()
