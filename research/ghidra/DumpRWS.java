// Decompile the RWS audio relocation (FUN_002AD8E0, crash pc 0x2ad97c) + the track-table
// consumer, to learn the per-track structure so new entries can be built correctly.
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.*;
import java.util.*;

public class DumpRWS extends GhidraScript {
    DecompInterface di;
    Set<Long> done = new HashSet<>();
    void dump(long t, int depth) throws Exception {
        if (done.contains(t)) return; done.add(t);
        Function f = getFunctionContaining(toAddr(t));
        if (f == null) f = createFunction(toAddr(t), null);
        println("\n===== @0x" + Long.toHexString(t) + (f != null ? "  " + f.getName() : "") + " =====");
        if (f == null) { println("  <none>"); return; }
        DecompileResults r = di.decompileFunction(f, 90, monitor);
        if (r != null && r.decompileCompleted()) println(r.getDecompiledFunction().getC());
        else { println("  <decompile failed>"); return; }
        if (depth > 0)
            for (Function c : f.getCalledFunctions(monitor))
                dump(c.getEntryPoint().getOffset(), depth - 1);
    }
    public void run() throws Exception {
        di = new DecompInterface(); di.openProgram(currentProgram);
        dump(0x2AD8E0L, 1);   // the RWS relocation (crash site)
    }
}
