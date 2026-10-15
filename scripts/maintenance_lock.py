"""Hold outputs/locks/maintenance.lock exclusively for scripts/relocate_checkout.sh.

    python3 scripts/maintenance_lock.py ROOT EXPECTED_INODE PARENT_PID

Prints "held" once locked (then stays until PARENT_PID is gone) or "busy" and exits 1.
The same rules as run_skill.py: the checkout must still be the one the caller checked
(EXPECTED_INODE), folders are created one level at a time (never recreating a moved
checkout), and the locked file must still be the one at its path (BUILD-007).
"""
import fcntl
import os
import sys
import time


def acquire(root: str, inode: int):
    try:
        if os.stat(root).st_ino != inode:
            return None
        for d in (os.path.join(root, "outputs"), os.path.join(root, "outputs", "locks")):
            try:
                os.mkdir(d)
            except FileExistsError:
                pass
        path = os.path.join(root, "outputs", "locks", "maintenance.lock")
        f = open(path, "a")
    except OSError:
        return None
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        if os.fstat(f.fileno()).st_ino != os.stat(path).st_ino or os.stat(root).st_ino != inode:
            raise OSError("checkout or lock moved")
    except OSError:
        f.close()
        return None
    return f


def main() -> int:
    root, inode, parent = sys.argv[1], int(sys.argv[2]), int(sys.argv[3])
    f = acquire(root, inode)
    if f is None:
        print("busy", flush=True)
        return 1
    print("held", flush=True)
    while os.getppid() == parent:
        time.sleep(0.5)
    return 0


if __name__ == "__main__":
    sys.exit(main())
