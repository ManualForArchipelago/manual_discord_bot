from collections import deque
from manual_checker.report import Report


def validate_regions(table: dict, report: Report) -> None:
    starting = []
    ignored = set()
    has_connections = False
    for name, data in table.items():
        if name == "$schema":
            ignored.add(name)
            continue
        if data.get("starting", False):
            starting.append(name)
        if data.get("connects_to", []):
            has_connections = True
    if starting:
        # Check that all regions are reachable
        connected = starting.copy()
        queue = deque(starting)
        while queue:
            current = queue.popleft()
            for region in table[current].get("connects_to", []):
                if region not in connected:
                    connected.append(region)
                    queue.append(region)

        unreachable = set(table.keys()) - set(connected) - ignored
        if unreachable:
            report.errors.setdefault("regions.json", [])
            if connected == starting:
                report.errors["regions.json"].append('All non-starting regions are unreachable.  Your "connects_to" might be backwards.')
            error = f"Unreachable regions: {', '.join(unreachable)}"
            if len(error) > 300:
                error = error[:297] + "..."
            report.errors["regions.json"].append(error)
    elif has_connections:
            report.errors.setdefault("regions.json", [])
            report.errors["regions.json"].append('"connects_to" has been used, but there are no starting regions defined.  Without a starting region, everything is connected to everything.')
