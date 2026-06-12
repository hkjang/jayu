import sys, traceback
sys.stdout.reconfigure(encoding='utf-8', errors='replace')
sys.stderr.reconfigure(encoding='utf-8', errors='replace')

try:
    import danta_simulation as sim
    sim.run()
except Exception as e:
    print(f"\n[FATAL ERROR] {e}")
    traceback.print_exc()
