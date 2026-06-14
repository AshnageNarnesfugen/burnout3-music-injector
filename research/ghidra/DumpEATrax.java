// Headless: decompile the EA TRAX functions to C pseudocode + dump XREFs.
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.Function;
import ghidra.program.model.symbol.Reference;

public class DumpEATrax extends GhidraScript {
    long[] targets = {
        0x3FBC20L, // path builder #1
        0x3FC2E0L, // path builder #2
        0x3FCD20L, // construct (count/array-base)
        0x3FC700L, // state machine
        0x271A00L  // string-id resolver
    };

    public void run() throws Exception {
        DecompInterface di = new DecompInterface();
        di.openProgram(currentProgram);
        for (long t : targets) {
            Address a = toAddr(t);
            Function f = getFunctionContaining(a);
            if (f == null) f = createFunction(a, null);
            println("\n================ FUNC @ 0x" + Long.toHexString(t)
                    + (f != null ? "  (" + f.getName() + ")" : "") + " ================");
            if (f == null) { println("  <no function>"); continue; }
            DecompileResults r = di.decompileFunction(f, 90, monitor);
            if (r != null && r.decompileCompleted()) {
                println(r.getDecompiledFunction().getC());
            } else {
                println("  <decompile failed: " + (r==null?"null":r.getErrorMessage()) + ">");
            }
        }
        // XREFs to key data so we can find the real file-open/loader call sites
        long[] data = { 0x4E1F08L, 0x4CEA90L, 0x4A5A24L, 0x4A5A6CL, 0x4A5600L };
        println("\n================ XREFS TO KEY DATA ================");
        for (long d : data) {
            Address a = toAddr(d);
            println("-> 0x" + Long.toHexString(d) + ":");
            Reference[] refs = getReferencesTo(a);
            int n = 0;
            for (Reference ref : refs) {
                Function cf = getFunctionContaining(ref.getFromAddress());
                println("     from 0x" + ref.getFromAddress() + " ("
                        + ref.getReferenceType() + (cf!=null?" in "+cf.getName():"") + ")");
                if (++n >= 12) break;
            }
        }
    }
}
