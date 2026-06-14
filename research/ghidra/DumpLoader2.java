// Find the file-open API (sceCd*/stream/file) + decompile the stream setup chain.
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.*;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import java.util.*;

public class DumpLoader2 extends GhidraScript {
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
        di = new DecompInterface();
        di.openProgram(currentProgram);

        // 1) symbols hinting the file/CD/stream API
        println("===== SYMBOLS matching cd/search/stream/file/open/rwstream =====");
        SymbolTable st = currentProgram.getSymbolTable();
        for (Symbol s : st.getAllSymbols(false)) {
            String n = s.getName().toLowerCase();
            if (n.contains("cdsearch") || n.contains("searchfile") || n.contains("scecd")
                || n.contains("rwstream") || n.contains("streamopen") || n.contains("fileio")
                || n.contains("filexio") || (n.contains("open") && n.contains("file"))
                || n.contains("cdread") || n.contains("loadfile"))
                println("  " + s.getName() + " @ " + s.getAddress());
        }

        // 2) the stream setup/teardown chain (called by the Prepare fns) + 1 level
        for (long t : new long[]{0x3fc700L, 0x386240L, 0x3863c0L, 0x386a60L})
            dump(t, 1);
    }
}
