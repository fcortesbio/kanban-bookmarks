# kanban-bookmarks

Restructure Firefox bookmarks from a **taxonomy-based** organization (by source: Coursera, Platzi, CISCO) to a **Kanban-based** structure (by status: In Progress, Planning, Archive).

## Why?

The traditional "where did I find this?" organization creates friction when you want to **execute**. A Kanban structure with WIP limits helps you:

- Focus on a limited number of active courses (default: 3)
- Maintain a clear backlog of planned courses
- Archive completed courses for reference

## Features

- **WIP Limit**: Enforces a limit of 3 active items in `01_IN_PROGRESS`
- **Smart Sorting**: Prioritizes by last visit date, then last modified, then visit count
- **Safe Operations**: Validates Firefox database invariants (unique GUIDs, positions)
- **Path-based Lookup**: Uses recursive CTEs to find folders by path (IDs vary across profiles)
- **Non-destructive**: Works on a copy; requires explicit confirmation to commit

## Usage

```bash
# 1. Close Firefox first!

# 2. Create a backup copy
cp ~/.mozilla/firefox/<profile>/places.sqlite /tmp/places_copy.sqlite

# 3. Run the script (edit DB_PATH in script if needed)
python3 restructure_bookmarks.py --dry-run    # Preview changes
python3 restructure_bookmarks.py --commit     # Auto-commit changes
python3 restructure_bookmarks.py              # Interactive mode

# 4. If satisfied, copy back (Firefox must be closed!)
cp /tmp/places_copy.sqlite ~/.mozilla/firefox/<profile>/places.sqlite
```

## Configuration

Edit the top of `restructure_bookmarks.py`:

```python
DB_PATH = Path("/tmp/places_copy.sqlite")  # Database location
TOOLBAR_PARENT_ID = 3                       # Firefox toolbar folder ID
WIP_LIMIT = 3                               # Max items in IN_PROGRESS
```

## Source Folders

The script looks for bookmarks in these paths (under Bookmarks Toolbar):

- `Learn / Coursera / In progress` → Active courses
- `Learn / Coursera / Planning` → Planned courses  
- `Learn / Coursera / Completed` → Archived courses
- `Learn / Platzi` → Treated as active
- `Learn / CISCO` → Treated as active

## Output Structure

```
Bookmarks Toolbar/
├── ... (existing folders)
├── 01_IN_PROGRESS/   # Top 3 most recently visited/modified
├── 02_PLANNING/      # Everything else
└── 03_ARCHIVE/       # Completed courses
```

## Firefox Database Notes

- **Timestamps**: Stored in microseconds (Unix timestamp × 1,000,000)
- **GUIDs**: 12-character alphanumeric strings, must be unique
- **Positions**: 0-indexed, must be unique within each folder
- **System folders** (IDs 1-6): Protected, do not modify
- **Type values**: 1 = bookmark, 2 = folder

## Dependencies

- Python 3.9+
- sqlite3 (standard library)

## License

MIT
