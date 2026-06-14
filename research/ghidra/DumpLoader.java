// Headless: decompile the file open/load/stream chain to see HOW the game resolves
// "tracks\_EATraxN.rws" (live directory search vs a cached file table).
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.*;
import java.util.*;

public class DumpLoader extends GhidraScript {
    DecompInterface di;
    Set<Long> done = new HashSet<>();

    void dump(long t, int depth) throws Exception {
        if (done.contains(t)) return;
        done.add(t);
        Address a = toAddr(t);
        Function f = getFunctionContaining(a);
        if (f == null) f = createFunction(a, null);
        println("\n===== @0x" + Long.toHexString(t) + (f != null ? "  " + f.getName() : "") + " =====");
        if (f == null) { println("  <no function>"); return; }
        DecompileResults r = di.decompileFunction(f, 120, monitor);
        if (r != null && r.decompileCompleted()) {
            println(r.getDecompiledFunction().getC());
        } else {
            println("  <decompile failed>");
            return;
        }
        if (depth > 0) {
            for (Function c : f.getCalledFunctions(monitor)) {
                dump(c.getEntryPoint().getOffset(), depth - 1);
            }
        }
    }

    public void run() throws Exception {
        di = new DecompInterface();
        di.openProgram(currentProgram);
        // open-by-path + one level of callees (reveals sceCdSearchFile / file-table cache)
        dump(0x386790L, 1);
        // the play state machine (issues the actual read/stream)
        dump(0x3FC8C0L, 1);
    }
}
