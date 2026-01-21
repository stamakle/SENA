import sys
import os
import json
from unittest.mock import MagicMock, patch

# Add project root to path
sys.path.insert(0, os.path.abspath(os.getcwd()))

from src.graph.graph import run_graph
from src.tools import ssh_client
from src.config import load_config

# Ensure we use the absolute path for config to avoid CWD issues
project_root = os.getcwd()
os.environ["SENA_SSH_CONFIG"] = os.path.join(project_root, "configs", "ssh.json")
# Set a dummy Live Path so we don't overwrite the user's actual session_live.json if they are using it
os.environ["SENA_LIVE_PATH"] = os.path.join(project_root, "verify_session_live.json")

def cleanup():
    if os.path.exists(os.environ["SENA_LIVE_PATH"]):
        os.remove(os.environ["SENA_LIVE_PATH"])

def test_flow():
    print("Testing Live Conversational RAG Flow...")
    cleanup()
    
    # 1. Test Command that was failing: dmesg | tail -n 50
    print("\n--- Step 1: Executing SSH Command '/ssh 192.168.1.1 \"dmesg | tail -n 50\"' ---")
    
    # We use a dummy IP so we don't rely on RAG hostname resolution
    target_cmd = "dmesg | tail -n 50"
    target_host = "192.168.1.1" 
    query = f'/ssh {target_host} "{target_cmd}"'
    
    # Patch Paramiko to simulate successful SSH connection and execution
    with patch("src.tools.ssh_client.paramiko.SSHClient") as mock_ssh_class, \
         patch("src.tools.ssh_client._resolve_target_from_rag", return_value={}) as mock_db_resolve:
        mock_client = mock_ssh_class.return_value
        
        # Setup mock stdout
        mock_stdout = MagicMock()
        mock_stdout.read.return_value = b"[ 123.456] Error: NVMe device failed verification\n[ 123.457] Some other kernel message"
        mock_stderr = MagicMock()
        mock_stderr.read.return_value = b""
        
        # connect, exec_command returns (stdin, stdout, stderr)
        mock_client.exec_command.return_value = (MagicMock(), mock_stdout, mock_stderr)
        
        # Run graph
        session_id = "verify_test_session"
        try:
            result = run_graph(query, session_id=session_id)
        except Exception as e:
            print(f"CRITICAL ERROR running graph: {e}")
            return

        print(f"Result Response: {result.response}")
        
        if "SSH result" in result.response and "NVMe device failed" in result.response:
            print("SUCCESS: Command passed allowlist and executed (mocked).")
        else:
            print("FAILURE: Command did not execute as expected.")
            if "not allowlisted" in result.response:
                print("Reason: Still not allowlisted. Check configs/ssh.json")
            return

    # 2. Test Conversational Follow-up
    print("\n--- Step 2: Testing Follow-up 'Analyze this log' ---")
    
    # The graph should have stored the result in live_memory (json file)
    followup_query = "Analyze this log and find the errors"
    
    # Patch retrieval_node in src.graph.graph because it's already imported there
    # This allows flow to proceed to 'response_node' which handles the live memory
    with patch("src.graph.graph.retrieval_node", return_value={}) as mock_retrieval:
        # Patch LLM chat_completion to avoid needing a real Ollama server
        with patch("src.graph.nodes.response.chat_completion") as mock_chat:
            mock_chat.return_value = "The log indicates an NVMe device failure at timestamp 123.456."
            
            result_followup = run_graph(followup_query, session_id=session_id)
            
            print(f"Follow-up Response: {result_followup.response}")
            
            # We verify that 'mock_chat' was called with the live output in the prompt.
            if mock_chat.call_count == 0:
                print("FAILURE: LLM was not called.")
                # Debug why: maybe response_node didn't see it as follow-up?
                return

            args, _ = mock_chat.call_args
            prompt_sent = args[3] # user_prompt is 4th arg (index 3)
            
            if "NVMe device failed" in prompt_sent:
                 print("SUCCESS: Live output was injected into the prompt context.")
            else:
                 print("FAILURE: Live output was NOT found in the prompt context.")
                 print(f"Prompt sent sample: {prompt_sent[:200]}...")

    cleanup()

if __name__ == "__main__":
    test_flow()
