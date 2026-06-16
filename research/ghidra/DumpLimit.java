// Find the game's internal EA-TRAX track-count limit: XREF the master count (0x4A5A24), the metadata
// base ptr (0x4A5A6C) and array (0x4A5600), then disassemble the referencing functions looking for a
// comparison against a constant (slti/sltiu/addiu) = the cap, or a fixed loop bound.
import ghidra.app.script.GhidraScript;
import ghidra.program.model.address.Address;
import ghidra.program.model.listing.*;
import ghidra.program.model.symbol.*;
import ghidra.program.model.scalar.Scalar;

public class DumpLimit extends GhidraScript {
    void dumpFn(Address a) throws Exception {
        Function f = getFunctionContaining(a);
        Address start = f != null ? f.getEntryPoint() : a.subtract(0x80);
        Address end = f != null ? f.getBody().getMaxAddress() : a.add(0x80);
        println("\n===== fn @0x" + (f!=null?Long.toHexString(f.getEntryPoint().getOffset()):"?")
                + " (xref near 0x" + Long.toHexString(a.getOffset()) + ") =====");
        Instruction ins = getInstructionAt(start);
        int n = 0;
        while (ins != null && ins.getAddress().compareTo(end) <= 0 && n++ < 400) {
            String m = ins.toString();
            // flag comparisons / immediates that could be the cap
            String mn = ins.getMnemonicString().toLowerCase();
            String flag = "";
            if (mn.startsWith("slti") || mn.equals("addiu") || mn.equals("li") || mn.startsWith("sltiu")) {
                for (int op = 0; op < ins.getNumOperands(); op++) {
                    Object[] o = ins.getOpObjects(op);
                    for (Object x : o) if (x instanceof Scalar) {
                        long v = ((Scalar)x).getUnsignedValue();
                        if (v >= 0x2C && v <= 0x100) flag = "   <<< imm=" + v + " (0x" + Long.toHexString(v) + ")";
                    }
                }
            }
            println(String.format("  %s  %s%s", ins.getAddress(), m, flag));
            ins = ins.getNext();
        }
    }
    public void run() throws Exception {
        long[] data = { 0x4A5A24L, 0x4A5A6CL, 0x4A5600L };
        for (long d : data) {
            println("\n################ XREFS to 0x" + Long.toHexString(d) + " ################");
            Reference[] refs = getReferencesTo(toAddr(d));
            java.util.HashSet<Long> seen = new java.util.HashSet<>();
            for (Reference r : refs) {
                Function f = getFunctionContaining(r.getFromAddress());
                long key = f != null ? f.getEntryPoint().getOffset() : r.getFromAddress().getOffset();
                if (seen.add(key)) dumpFn(r.getFromAddress());
            }
        }
    }
}
