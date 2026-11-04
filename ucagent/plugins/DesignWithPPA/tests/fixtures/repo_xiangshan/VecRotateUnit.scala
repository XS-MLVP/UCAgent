/** Unit boundary for the actual XiangShan VecRotate dependency. */
import chisel3._
import chisel3.util._
import _root_.circt.stage.ChiselStage
import utils.VecRotate

class VecRotateUnit extends RawModule {
  val data = IO(Input(UInt(64.W)))
  val amount = IO(Input(UInt(3.W)))
  val left = IO(Input(Bool()))
  val result = IO(Output(UInt(64.W)))
  val lanes = data.asTypeOf(Vec(8, UInt(8.W)))
  val rightResult = VecRotate(amount).rotate(lanes)
  val leftResult = VecRotate(amount, direction = VecRotate.Direction.Left).rotate(lanes)
  result := Mux(left, leftResult.asUInt, rightResult.asUInt)
}

/** Emit the unit without instantiating the XiangShan system. */
object UnitMain extends App {
  ChiselStage.emitSystemVerilogFile(new VecRotateUnit,
    Array("--target-dir", "unit-rtl"),
    Array("--disable-all-randomization", "--strip-debug-info",
      "--lowering-options=disallowLocalVariables,disallowPackedArrays"))
}
