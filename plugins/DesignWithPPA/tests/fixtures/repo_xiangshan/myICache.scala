/** Elastic bank-reordering unit; this is not a complete instruction cache. */
package xiangshan.frontend.icache

import chisel3._
import chisel3.util._
import utils.VecRotate

class myICache extends Module {
  val req_valid = IO(Input(Bool()))
  val req_ready = IO(Output(Bool()))
  val data = IO(Input(UInt(64.W)))
  val amount = IO(Input(UInt(3.W)))
  val left = IO(Input(Bool()))
  val resp_valid = IO(Output(Bool()))
  val resp_ready = IO(Input(Bool()))
  val result = IO(Output(UInt(64.W)))

  val pending = RegInit(false.B)
  val stored = Reg(UInt(64.W))
  val lanes = data.asTypeOf(Vec(8, UInt(8.W)))
  val rightResult = VecRotate(amount).rotate(lanes)
  val leftResult = VecRotate(amount, direction = VecRotate.Direction.Left).rotate(lanes)
  req_ready := !pending || resp_ready
  resp_valid := pending
  result := stored
  when(req_ready) {
    pending := req_valid
    when(req_valid) {
      stored := Mux(left, leftResult.asUInt, rightResult.asUInt)
    }
  }
}
