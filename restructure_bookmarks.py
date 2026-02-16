#!/usr/bin/env python3
"""
Firefox Bookmarks Restructure Script
=====================================
Transforms a taxonomy-based bookmark structure (by source: Coursera, Platzi, CISCO)
into a Kanban-based structure (by status: In Progress, Planning, Archive).

Goal:
- Create 01_IN_PROGRESS, 02_PLANNING, 03_ARCHIVE folders in Bookmarks Toolbar
- Move bookmarks from Learn/Coursera, Learn/Platzi, Learn/CISCO
- Enforce WIP limit of 3 for 01_IN_PROGRESS (most recently visited/modified)

Safety:
- Works on a copy of the database
- Validates invariants before and after
- Creates detailed report of changes

Usage:
    python3 restructure_bookmarks.py           # Interactive mode (prompts for confirmation)
    python3 restructure_bookmarks.py --commit  # Auto-commit changes
    python3 restructure_bookmarks.py --dry-run # Show what would happen without committing
"""

import sqlite3
import random
import string
import time
import sys
from pathlib import Path
from dataclasses import dataclass
from typing import Optional


# Configuration
DB_PATH = Path("/tmp/places_copy.sqlite")
TOOLBAR_PARENT_ID = 3
WIP_LIMIT = 3
SYSTEM_FOLDER_IDS = {1, 2, 3, 4, 5, 6}  # Protected Firefox system folders

# New folder names (ordered for toolbar position)
NEW_FOLDERS = [
    ("01_IN_PROGRESS", "Active courses - WIP limit of 3"),
    ("02_PLANNING", "Queued courses to start later"),
    ("03_ARCHIVE", "Completed courses"),
]


@dataclass
class Bookmark:
    """Represents a bookmark or folder."""
    id: int
    title: str
    parent: int
    position: int
    type: int  # 1=bookmark, 2=folder
    fk: Optional[int]  # foreign key to moz_places
    guid: str
    url: Optional[str] = None
    visit_count: int = 0
    last_visit_date: Optional[int] = None
    last_modified: Optional[int] = None


def generate_guid() -> str:
    """Generate a 12-character alphanumeric GUID for Firefox bookmarks."""
    chars = string.ascii_letters + string.digits
    return ''.join(random.choice(chars) for _ in range(12))


def get_timestamp_microseconds() -> int:
    """Get current timestamp in microseconds (Firefox format)."""
    return int(time.time() * 1_000_000)


def validate_unique_positions(conn: sqlite3.Connection, parent_id: int) -> bool:
    """Validate that all items in a folder have unique positions."""
    cursor = conn.execute(
        "SELECT position, COUNT(*) as cnt FROM moz_bookmarks WHERE parent = ? GROUP BY position HAVING cnt > 1",
        (parent_id,)
    )
    duplicates = cursor.fetchall()
    return len(duplicates) == 0


def validate_unique_guids(conn: sqlite3.Connection) -> bool:
    """Validate that all GUIDs are unique."""
    cursor = conn.execute(
        "SELECT guid, COUNT(*) as cnt FROM moz_bookmarks GROUP BY guid HAVING cnt > 1"
    )
    duplicates = cursor.fetchall()
    return len(duplicates) == 0


def get_folder_id_by_path(conn: sqlite3.Connection, path_parts: list[str]) -> Optional[int]:
    """
    Find a folder ID by its path using recursive CTE.
    path_parts: e.g., ["toolbar", "Learn", "Coursera"]
    """
    if not path_parts:
        return None
    
    # Build the recursive CTE to traverse the path
    query = """
    WITH RECURSIVE folder_path AS (
        -- Start from root (parent=1)
        SELECT id, title, parent, 1 as depth
        FROM moz_bookmarks
        WHERE parent = 1 AND title = ?
        
        UNION ALL
        
        SELECT b.id, b.title, b.parent, fp.depth + 1
        FROM moz_bookmarks b
        INNER JOIN folder_path fp ON b.parent = fp.id
        WHERE b.type = 2  -- folders only
    )
    SELECT id FROM folder_path WHERE title = ? AND depth = ?
    """
    
    # Navigate down the path
    current_id = None
    for depth, part in enumerate(path_parts, start=1):
        if depth == 1:
            cursor = conn.execute(
                "SELECT id FROM moz_bookmarks WHERE parent = 1 AND title = ?",
                (part,)
            )
        else:
            cursor = conn.execute(
                "SELECT id FROM moz_bookmarks WHERE parent = ? AND title = ? AND type = 2",
                (current_id, part)
            )
        result = cursor.fetchone()
        if result is None:
            return None
        current_id = result[0]
    
    return current_id


def folder_exists(conn: sqlite3.Connection, parent_id: int, title: str) -> Optional[int]:
    """Check if a folder with given title exists under parent. Returns folder ID or None."""
    cursor = conn.execute(
        "SELECT id FROM moz_bookmarks WHERE parent = ? AND title = ? AND type = 2",
        (parent_id, title)
    )
    result = cursor.fetchone()
    return result[0] if result else None


def get_max_position(conn: sqlite3.Connection, parent_id: int) -> int:
    """Get the maximum position value in a folder."""
    cursor = conn.execute(
        "SELECT COALESCE(MAX(position), -1) FROM moz_bookmarks WHERE parent = ?",
        (parent_id,)
    )
    return cursor.fetchone()[0]


def create_folder(conn: sqlite3.Connection, parent_id: int, title: str, position: int) -> int:
    """Create a new folder and return its ID."""
    guid = generate_guid()
    now = get_timestamp_microseconds()
    
    # Ensure GUID is unique
    while True:
        cursor = conn.execute("SELECT 1 FROM moz_bookmarks WHERE guid = ?", (guid,))
        if cursor.fetchone() is None:
            break
        guid = generate_guid()
    
    conn.execute("""
        INSERT INTO moz_bookmarks (type, fk, parent, position, title, dateAdded, lastModified, guid)
        VALUES (2, NULL, ?, ?, ?, ?, ?, ?)
    """, (parent_id, position, title, now, now, guid))
    
    cursor = conn.execute("SELECT last_insert_rowid()")
    return cursor.fetchone()[0]


def get_bookmarks_in_folder(conn: sqlite3.Connection, folder_id: int, recursive: bool = False) -> list[Bookmark]:
    """Get all bookmarks in a folder. If recursive, include subfolders."""
    if recursive:
        query = """
        WITH RECURSIVE folder_tree AS (
            SELECT id FROM moz_bookmarks WHERE id = ?
            UNION ALL
            SELECT b.id FROM moz_bookmarks b
            INNER JOIN folder_tree ft ON b.parent = ft.id
            WHERE b.type = 2
        )
        SELECT b.id, b.title, b.parent, b.position, b.type, b.fk, b.guid, b.lastModified,
               p.url, p.visit_count, p.last_visit_date
        FROM moz_bookmarks b
        LEFT JOIN moz_places p ON b.fk = p.id
        WHERE b.parent IN (SELECT id FROM folder_tree) AND b.type = 1
        """
        cursor = conn.execute(query, (folder_id,))
    else:
        cursor = conn.execute("""
            SELECT b.id, b.title, b.parent, b.position, b.type, b.fk, b.guid, b.lastModified,
                   p.url, p.visit_count, p.last_visit_date
            FROM moz_bookmarks b
            LEFT JOIN moz_places p ON b.fk = p.id
            WHERE b.parent = ? AND b.type = 1
        """, (folder_id,))
    
    bookmarks = []
    for row in cursor.fetchall():
        bookmarks.append(Bookmark(
            id=row[0],
            title=row[1],
            parent=row[2],
            position=row[3],
            type=row[4],
            fk=row[5],
            guid=row[6],
            last_modified=row[7],
            url=row[8],
            visit_count=row[9] or 0,
            last_visit_date=row[10]
        ))
    return bookmarks


def move_bookmark(conn: sqlite3.Connection, bookmark_id: int, new_parent: int, new_position: int):
    """Move a bookmark to a new folder with a new position."""
    now = get_timestamp_microseconds()
    conn.execute("""
        UPDATE moz_bookmarks
        SET parent = ?, position = ?, lastModified = ?
        WHERE id = ?
    """, (new_parent, new_position, now, bookmark_id))


def reindex_positions(conn: sqlite3.Connection, parent_id: int):
    """Reindex positions in a folder to be sequential starting from 0."""
    cursor = conn.execute(
        "SELECT id FROM moz_bookmarks WHERE parent = ? ORDER BY position",
        (parent_id,)
    )
    for new_pos, (item_id,) in enumerate(cursor.fetchall()):
        conn.execute(
            "UPDATE moz_bookmarks SET position = ? WHERE id = ?",
            (new_pos, item_id)
        )


def get_folder_contents_report(conn: sqlite3.Connection, folder_id: int, folder_title: str) -> list[str]:
    """Generate a report of folder contents."""
    bookmarks = get_bookmarks_in_folder(conn, folder_id)
    lines = [f"\n  {folder_title} ({len(bookmarks)} items):"]
    for b in sorted(bookmarks, key=lambda x: x.position):
        visit_info = f"visits={b.visit_count}" if b.visit_count else "unvisited"
        lines.append(f"    [{b.position}] {b.title[:60]}... ({visit_info})")
    return lines


def main():
    # Parse command line arguments
    auto_commit = '--commit' in sys.argv
    dry_run = '--dry-run' in sys.argv
    
    print("=" * 70)
    print("Firefox Bookmarks Restructure Script")
    if dry_run:
        print("MODE: DRY RUN (no changes will be made)")
    elif auto_commit:
        print("MODE: AUTO-COMMIT")
    else:
        print("MODE: INTERACTIVE")
    print("=" * 70)
    
    if not DB_PATH.exists():
        print(f"ERROR: Database not found at {DB_PATH}")
        return 1
    
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    
    try:
        # ================================================================
        # PHASE 1: Validate initial state
        # ================================================================
        print("\n[PHASE 1] Validating initial database state...")
        
        if not validate_unique_guids(conn):
            print("ERROR: Database has duplicate GUIDs!")
            return 1
        print("  ✓ All GUIDs are unique")
        
        if not validate_unique_positions(conn, TOOLBAR_PARENT_ID):
            print("WARNING: Toolbar has duplicate positions, will reindex")
            reindex_positions(conn, TOOLBAR_PARENT_ID)
        print("  ✓ Toolbar positions are valid")
        
        # ================================================================
        # PHASE 2: Locate source folders using recursive CTE
        # ================================================================
        print("\n[PHASE 2] Locating source folders...")
        
        source_folders = {
            "coursera_in_progress": ["toolbar", "Learn", "Coursera", "In progress"],
            "coursera_planning": ["toolbar", "Learn", "Coursera", "Planning"],
            "coursera_completed": ["toolbar", "Learn", "Coursera", "Completed"],
            "platzi": ["toolbar", "Learn", "Platzi"],
            "cisco": ["toolbar", "Learn", "CISCO"],
        }
        
        folder_ids = {}
        for key, path in source_folders.items():
            folder_id = get_folder_id_by_path(conn, path)
            folder_ids[key] = folder_id
            status = f"id={folder_id}" if folder_id else "NOT FOUND"
            # Sanitize path display by removing "toolbar / "
            display_path = " / ".join(path[1:]) if len(path) > 1 else path[0]
            print(f"  {display_path}: {status}")
        
        # ================================================================
        # PHASE 3: Create new Kanban folders (if they don't exist)
        # ================================================================
        print("\n[PHASE 3] Creating Kanban folders in toolbar...")
        
        max_pos = get_max_position(conn, TOOLBAR_PARENT_ID)
        new_folder_ids = {}
        
        for i, (folder_name, description) in enumerate(NEW_FOLDERS):
            existing_id = folder_exists(conn, TOOLBAR_PARENT_ID, folder_name)
            if existing_id:
                print(f"  {folder_name}: EXISTS (id={existing_id})")
                new_folder_ids[folder_name] = existing_id
            else:
                new_pos = max_pos + 1 + i
                new_id = create_folder(conn, TOOLBAR_PARENT_ID, folder_name, new_pos)
                print(f"  {folder_name}: CREATED (id={new_id}, position={new_pos})")
                new_folder_ids[folder_name] = new_id
        
        # ================================================================
        # PHASE 4: Collect all bookmarks from source folders
        # ================================================================
        print("\n[PHASE 4] Collecting bookmarks from source folders...")
        
        all_bookmarks = []
        completed_bookmarks = []
        
        # Coursera In Progress -> considered active
        if folder_ids["coursera_in_progress"]:
            bookmarks = get_bookmarks_in_folder(conn, folder_ids["coursera_in_progress"])
            print(f"  Coursera/In progress: {len(bookmarks)} bookmarks")
            all_bookmarks.extend(bookmarks)
        
        # Coursera Planning -> considered planning
        if folder_ids["coursera_planning"]:
            bookmarks = get_bookmarks_in_folder(conn, folder_ids["coursera_planning"])
            print(f"  Coursera/Planning: {len(bookmarks)} bookmarks")
            all_bookmarks.extend(bookmarks)
        
        # Coursera Completed -> goes to archive
        if folder_ids["coursera_completed"]:
            bookmarks = get_bookmarks_in_folder(conn, folder_ids["coursera_completed"])
            print(f"  Coursera/Completed: {len(bookmarks)} bookmarks")
            completed_bookmarks.extend(bookmarks)
        
        # Platzi bookmarks -> considered active
        if folder_ids["platzi"]:
            bookmarks = get_bookmarks_in_folder(conn, folder_ids["platzi"], recursive=True)
            print(f"  Platzi (recursive): {len(bookmarks)} bookmarks")
            all_bookmarks.extend(bookmarks)
        
        # CISCO bookmarks -> considered active
        if folder_ids["cisco"]:
            bookmarks = get_bookmarks_in_folder(conn, folder_ids["cisco"], recursive=True)
            print(f"  CISCO (recursive): {len(bookmarks)} bookmarks")
            all_bookmarks.extend(bookmarks)
        
        print(f"\n  Total active/planning bookmarks: {len(all_bookmarks)}")
        print(f"  Total completed bookmarks: {len(completed_bookmarks)}")
        
        # ================================================================
        # PHASE 5: Sort by recency and apply WIP limit
        # ================================================================
        print("\n[PHASE 5] Applying WIP limit logic...")
        
        # Sort by: last_visit_date DESC, last_modified DESC, visit_count DESC
        def sort_key(b: Bookmark):
            return (
                b.last_visit_date or 0,
                b.last_modified or 0,
                b.visit_count
            )
        
        all_bookmarks.sort(key=sort_key, reverse=True)
        
        # Split into WIP (top 3) and Planning (rest)
        in_progress_bookmarks = all_bookmarks[:WIP_LIMIT]
        planning_bookmarks = all_bookmarks[WIP_LIMIT:]
        
        print(f"  01_IN_PROGRESS: {len(in_progress_bookmarks)} bookmarks (WIP limit = {WIP_LIMIT})")
        print(f"  02_PLANNING: {len(planning_bookmarks)} bookmarks")
        print(f"  03_ARCHIVE: {len(completed_bookmarks)} bookmarks")
        
        # Show what's going to IN_PROGRESS
        print("\n  Bookmarks selected for IN_PROGRESS (most recent):")
        for b in in_progress_bookmarks:
            visit_str = f"visits={b.visit_count}" if b.visit_count else "unvisited"
            print(f"    - {b.title[:50]}... ({visit_str})")
        
        # ================================================================
        # PHASE 6: Move bookmarks to new folders
        # ================================================================
        print("\n[PHASE 6] Moving bookmarks...")
        
        moves = []
        
        # Move to IN_PROGRESS
        target_id = new_folder_ids["01_IN_PROGRESS"]
        for pos, bookmark in enumerate(in_progress_bookmarks):
            move_bookmark(conn, bookmark.id, target_id, pos)
            moves.append((bookmark.title, "01_IN_PROGRESS"))
        
        # Move to PLANNING
        target_id = new_folder_ids["02_PLANNING"]
        for pos, bookmark in enumerate(planning_bookmarks):
            move_bookmark(conn, bookmark.id, target_id, pos)
            moves.append((bookmark.title, "02_PLANNING"))
        
        # Move to ARCHIVE
        target_id = new_folder_ids["03_ARCHIVE"]
        for pos, bookmark in enumerate(completed_bookmarks):
            move_bookmark(conn, bookmark.id, target_id, pos)
            moves.append((bookmark.title, "03_ARCHIVE"))
        
        print(f"  Moved {len(moves)} bookmarks total")
        
        # ================================================================
        # PHASE 7: Validate final state
        # ================================================================
        print("\n[PHASE 7] Validating final database state...")
        
        errors = []
        
        if not validate_unique_guids(conn):
            errors.append("Duplicate GUIDs detected!")
        else:
            print("  ✓ All GUIDs are unique")
        
        for folder_name, folder_id in new_folder_ids.items():
            if not validate_unique_positions(conn, folder_id):
                errors.append(f"Duplicate positions in {folder_name}!")
            else:
                print(f"  ✓ {folder_name} positions are valid")
        
        if errors:
            print("\nERRORS DETECTED - Rolling back!")
            for err in errors:
                print(f"  ✗ {err}")
            conn.rollback()
            return 1
        
        # ================================================================
        # PHASE 8: Generate report
        # ================================================================
        print("\n[PHASE 8] Final structure report...")
        
        for folder_name, folder_id in new_folder_ids.items():
            for line in get_folder_contents_report(conn, folder_id, folder_name):
                print(line)
        
        # ================================================================
        # PHASE 9: Commit changes
        # ================================================================
        print("\n" + "=" * 70)
        
        if dry_run:
            print("DRY RUN COMPLETE - Rolling back all changes")
            print("=" * 70)
            conn.rollback()
            print("\n✗ No changes made (dry run mode)")
        elif auto_commit:
            print("AUTO-COMMIT: All validations passed")
            print("=" * 70)
            conn.commit()
            print("\n✓ Changes committed successfully!")
            print(f"  Database: {DB_PATH}")
        else:
            print("COMMIT CHANGES? All validations passed.")
            print("=" * 70)
            response = input("Type 'yes' to commit, anything else to rollback: ").strip().lower()
            
            if response == 'yes':
                conn.commit()
                print("\n✓ Changes committed successfully!")
                print(f"  Database: {DB_PATH}")
            else:
                conn.rollback()
                print("\n✗ Changes rolled back (no modifications made)")
        
        return 0
        
    except Exception as e:
        print(f"\nERROR: {e}")
        conn.rollback()
        raise
    finally:
        conn.close()


if __name__ == "__main__":
    exit(main())
