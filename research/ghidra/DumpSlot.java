// Decompile the 1180-byte career "slot"/profile record helpers to determine the record's real used
// size and whether the reserved window (offset ~225..896) is ever touched — the region fix (b) reuses.
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.listing.Function;

public class DumpSlot extends GhidraScript {
    public void run() throws Exception {
        long[] addrs = {
            0x13b820L,  // record init (called on each slot / on the runtime record)
            0x13b730L,  // get checksum field
            0x13b740L,  // set checksum field
            0x13a560L,  // per-slot id/checksum computation
            0x13a570L,  // sibling of 13a560
            0x139c00L,  // post-load process #1
            0x139f20L,  // post-load process #2
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
