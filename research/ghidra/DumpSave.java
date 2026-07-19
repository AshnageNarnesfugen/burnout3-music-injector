// Decompile the memory-card SAVE/LOAD functions to map the profile blob structure and, crucially,
// decide whether the 1180-byte profile "slot" record's reserved zero-window (offset ~225..896) is
// ever written by the game — the region fix (b) wants to reuse for the >44 play-loc extras.
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.listing.Function;

public class DumpSave extends GhidraScript {
    public void run() throws Exception {
        long[] addrs = {
            0x421AF0L,  // serialize (save profile) -> writes blob + global checksum
            0x421850L,  // deserialize (load profile) -> distributes blob to runtime
            0x421700L,  // load validation (global checksum + per-slot id check)
            0x421000L,  // load caller
            0x421060L,  // save caller (a3 gate)
            0x420FE0L,  // slot address helper (mult 1180)
        };
        DecompInterface di = new DecompInterface();
        di.toggleCCode(true);
        di.openProgram(currentProgram);
        for (long a : addrs) {
            Function f = getFunctionContaining(toAddr(a));
            if (f == null) { println("\n==== NO FUNCTION @0x" + Long.toHexString(a) + " ===="); continue; }
            println("\n==== fn @0x" + Long.toHexString(f.getEntryPoint().getOffset())
                    + "  (probe 0x" + Long.toHexString(a) + ", " + f.getBody().getNumAddresses() + " bytes) ====");
            DecompileResults r = di.decompileFunction(f, 240, monitor);
            if (r.decompileCompleted()) println(r.getDecompiledFunction().getC());
            else println("DECOMPILE FAILED: " + r.getErrorMessage());
        }
    }
}
