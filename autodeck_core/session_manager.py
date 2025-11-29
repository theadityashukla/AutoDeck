import os
import json
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Any
from pathlib import Path

class SessionManager:
    def __init__(self, sessions_dir: str = "sessions"):
        """Initialize the SessionManager with a directory for session storage."""
        self.sessions_dir = Path(sessions_dir)
        self.sessions_dir.mkdir(exist_ok=True)
        self.max_sessions = 10
    
    def create_new_session(self, name: Optional[str] = None) -> str:
        """Create a new session and return its ID."""
        session_id = str(uuid.uuid4())[:8]  # Short UUID
        if name is None:
            name = f"Session {datetime.now().strftime('%Y-%m-%d %H:%M')}"
        
        session_data = {
            "id": session_id,
            "name": name,
            "created_at": datetime.now().isoformat(),
            "last_modified": datetime.now().isoformat(),
            "outline": [],
            "content": {},
            "logs": [],
            "slide_comments": {}
        }
        
        self._save_to_disk(session_id, session_data)
        self._cleanup_old_sessions()
        return session_id
    
    def save_session(self, session_id: str, data: Dict[str, Any]) -> bool:
        """Save session data to disk."""
        try:
            session_path = self.sessions_dir / f"{session_id}.json"
            
            # Load existing session or create new metadata
            if session_path.exists():
                with open(session_path, 'r') as f:
                    existing = json.load(f)
                    created_at = existing.get("created_at", datetime.now().isoformat())
                    name = existing.get("name", f"Session {session_id}")
            else:
                created_at = datetime.now().isoformat()
                name = data.get("name", f"Session {session_id}")
            
            # Update session data
            session_data = {
                "id": session_id,
                "name": name,
                "created_at": created_at,
                "last_modified": datetime.now().isoformat(),
                "outline": data.get("outline", []),
                "content": data.get("content", {}),
                "logs": data.get("logs", []),
                "slide_comments": data.get("slide_comments", {})
            }
            
            self._save_to_disk(session_id, session_data)
            self._cleanup_old_sessions()
            return True
        except Exception as e:
            print(f"Error saving session {session_id}: {e}")
            return False
    
    def load_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Load session data from disk."""
        try:
            session_path = self.sessions_dir / f"{session_id}.json"
            if not session_path.exists():
                return None
            
            with open(session_path, 'r') as f:
                return json.load(f)
        except Exception as e:
            print(f"Error loading session {session_id}: {e}")
            return None
    
    def list_sessions(self) -> List[Dict[str, Any]]:
        """List all sessions, sorted by last modified (newest first)."""
        sessions = []
        
        for session_file in self.sessions_dir.glob("*.json"):
            try:
                with open(session_file, 'r') as f:
                    data = json.load(f)
                    sessions.append({
                        "id": data["id"],
                        "name": data["name"],
                        "created_at": data["created_at"],
                        "last_modified": data["last_modified"],
                        "slide_count": len(data.get("outline", [])),
                        "log_count": len(data.get("logs", []))
                    })
            except Exception as e:
                print(f"Error reading session file {session_file}: {e}")
        
        # Sort by last modified (newest first)
        sessions.sort(key=lambda x: x["last_modified"], reverse=True)
        return sessions
    
    def delete_session(self, session_id: str) -> bool:
        """Delete a session."""
        try:
            session_path = self.sessions_dir / f"{session_id}.json"
            if session_path.exists():
                session_path.unlink()
                return True
            return False
        except Exception as e:
            print(f"Error deleting session {session_id}: {e}")
            return False
    
    def rename_session(self, session_id: str, new_name: str) -> bool:
        """Rename a session."""
        try:
            session_data = self.load_session(session_id)
            if session_data:
                session_data["name"] = new_name
                session_data["last_modified"] = datetime.now().isoformat()
                self._save_to_disk(session_id, session_data)
                return True
            return False
        except Exception as e:
            print(f"Error renaming session {session_id}: {e}")
            return False
    
    def _save_to_disk(self, session_id: str, data: Dict[str, Any]) -> None:
        """Internal method to save session data to disk."""
        session_path = self.sessions_dir / f"{session_id}.json"
        with open(session_path, 'w') as f:
            json.dump(data, f, indent=2)
    
    def _cleanup_old_sessions(self) -> None:
        """Remove oldest sessions if we exceed max_sessions."""
        sessions = self.list_sessions()
        if len(sessions) > self.max_sessions:
            # Delete oldest sessions
            sessions_to_delete = sessions[self.max_sessions:]
            for session in sessions_to_delete:
                self.delete_session(session["id"])
