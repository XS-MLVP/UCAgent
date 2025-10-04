/*
 * Module: IntegerDivider
 * Author: wangjunyue2001@gmail.com
 * Description: Radix-4 SRT divider compliant with the RISCV-32M specification
 */

package divider

import spinal.core._
import spinal.lib.fsm._

import scala.language.postfixOps

case class IntegerDivider() extends Module {
  val io = new Bundle {
    val valid    = in Bool ()
    val flush    = in Bool ()
    val signed   = in Bool ()
    val useRem   = in Bool ()
    val dividend = in UInt (32 bits)
    val divisor  = in UInt (32 bits)
    val ready    = out Bool ()
    val done     = out Bool ()
    val result   = out UInt (32 bits)
  }
  // Control signal
  private val startDiv = Bool()
  // Modules
  private val pre   = PreProcess()
  private val stage = DivStage()
  private val post  = PostProcess()
  // Connection of pre-process
  pre.io.valid    := startDiv
  pre.io.signed   := io.signed
  pre.io.dividend := io.dividend
  pre.io.divisor  := io.divisor
  // Connection of div stage
  stage.io.valid := startDiv
  stage.io.divX  := pre.io.divX
  stage.io.divD  := pre.io.divD
  // Connection of post-process
  post.io.valid    := startDiv
  post.io.dividend := io.dividend
  post.io.divD     := pre.io.divD
  post.io.negX     := pre.io.negX
  post.io.negD     := pre.io.negD
  post.io.shiftR   := pre.io.shiftR
  post.io.ALTB     := pre.io.ALTB
  post.io.div0     := pre.io.div0
  post.io.overflow := pre.io.overflow
  post.io.qsm      := stage.io.qsm
  post.io.sum      := stage.io.sum
  post.io.carry    := stage.io.carry
  // State machine
  private val fsm = new StateMachine {
    val IDLE = makeInstantEntry()
    val BUSY = new State
    val DONE = new State
    // Division cycles
    private val cnt = Reg(UInt(5 bits))
    IDLE.whenIsActive {
      when(startDiv) {
        when(pre.io.special) {
          // Special case(ALTB, div0, overflow) happen
          goto(DONE)
        }.otherwise {
          // Normal case
          cnt := pre.io.cycle
          goto(BUSY)
        }
      }
    }
    BUSY.whenIsActive {
      cnt := cnt - 1
      when(io.flush) {
        goto(IDLE)
      }.elsewhen(cnt === U(0)) {
        goto(DONE)
      }
    }
    DONE.whenIsActive {
      goto(IDLE)
    }
  }
  io.done := fsm.isActive(fsm.DONE)
  private val idle = fsm.isActive(fsm.IDLE)
  io.ready := idle
  startDiv := idle && io.valid && !io.flush
  private val quotient = post.io.quotient
  private val reminder = post.io.reminder
  io.result := Mux(io.useRem, reminder, quotient)
}
