from collections import deque
from manual_checker.report import Report


def validate_regions(table: dict, report: Report) -> None:
    starting = []
    for name, data in table.items():
        if name == "$schema":
            continue
        if data.get("starting", False):
            starting.append(name)
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

        unreachable = set(table.keys()) - set(connected)
        if unreachable:
            report.errors.setdefault("regions.json", [])
            if connected == starting:
                report.errors["regions.json"].append('All non-starting regions are unreachable.  Your "connects_to" might be backwards.')
            report.errors["regions.json"].append(f"Unreachable regions: {', '.join(unreachable)}")
