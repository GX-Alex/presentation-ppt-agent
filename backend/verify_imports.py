"""Quick import verification for webdeck_runtime modules."""
import inspect

from app.services.webdeck_runtime.director import DeckDirector
from app.services.webdeck_runtime.contracts import DeckManifest, PageBundle, DeckShellConfig
from app.services.webdeck_runtime.planner import DeckPlanner
from app.services.webdeck_runtime.scheduler import LaneScheduler
from app.services.webdeck_runtime.page_orchestrator import PageOrchestrator
from app.services.webdeck_runtime.lane_runner import LaneRunner
from app.services.webdeck_runtime.artifact_composer import DeckComposer
from app.services.webdeck_runtime.state_store import deck_state_store

print("✅ All webdeck_runtime imports successful")

sig = inspect.signature(DeckDirector.__init__)
print(f"DeckDirector.__init__ params: {list(sig.parameters.keys())}")

sig_run = inspect.signature(DeckDirector.run)
print(f"DeckDirector.run params: {list(sig_run.parameters.keys())}")

sig_exec = inspect.signature(DeckDirector.execute_generation)
print(f"DeckDirector.execute_generation params: {list(sig_exec.parameters.keys())}")

sig_retry_p = inspect.signature(DeckDirector.retry_page)
print(f"DeckDirector.retry_page params: {list(sig_retry_p.parameters.keys())}")

sig_retry_l = inspect.signature(DeckDirector.retry_lane)
print(f"DeckDirector.retry_lane params: {list(sig_retry_l.parameters.keys())}")
