"""Shared archive scope: all DMs and exactly one guild's channels/threads.

Old archived data outside scope is retained in SQLite but never used for
completion or percentage calculations.
"""
TARGET_GUILD="804408079940583475"

def selected_parent_ids(db):
    return {str(row[0]) for row in db.execute(
        "SELECT id FROM channels WHERE kind=?", (f"guild:{TARGET_GUILD}",))}

def selected_kind(kind, parents):
    return (kind in ("dms",f"guild:{TARGET_GUILD}",f"threads-active:{TARGET_GUILD}")
            or any(kind == f"archived-{type_}:{pid}"
                   for pid in parents for type_ in ("public","private")))

def selected_rows(db):
    parents=selected_parent_ids(db)
    return [row for row in db.execute("SELECT * FROM channels")
            if selected_kind(row["kind"],parents)]

def selected_scan(scope,parents):
    return (scope in ("dms","guilds",f"guild:{TARGET_GUILD}",f"threads-active:{TARGET_GUILD}")
            or any(scope == f"archived-{type_}:{pid}"
                   for pid in parents for type_ in ("public","private")))
