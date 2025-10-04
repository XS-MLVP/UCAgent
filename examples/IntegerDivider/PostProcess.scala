/*
 * Module: PostProcess
 * Author: wangjunyue2001@gmail.com
 * Description:
 *  Performs final remainder and quotient correction for radix-4 SRT divider, including
 *  sign adjustment and special case handling (division by zero, overflow, etc.)
 */

package divider

import spinal.core._

import scala.language.postfixOps

case class PostProcess() extends Module {
  val io = new Bundle {
    val valid = in Bool ()
    // From pipeline
    val dividend = in UInt (32 bits)
    // From postProcess
    val divD     = in UInt (36 bits)
    val negX     = in Bool ()
    val negD     = in Bool ()
    val shiftR   = in UInt (6 bits)
    val ALTB     = in Bool ()
    val div0     = in Bool () // Divisor is zero
    val overflow = in Bool () // Overflow: The most-negative integer is divided by -1
    // From divStage
    val qsm      = in UInt (4 bits)
    val sum      = in UInt (36 bits)
    val carry    = in UInt (36 bits)
    val reminder = out UInt (32 bits)
    val quotient = out UInt (32 bits)
  }
  private val conv = DivConverter() // On the fly convert
  conv.io.valid := io.valid
  conv.io.qsm   := io.qsm
  // Reminder
  private val sumR = io.sum + io.carry
  private val negR = sumR.msb
  private val reminder = new Area {
    private val D = Mux(negR, io.divD, U(0)) |<< 2
    // When dividend >= 0, if sum >= 0, don't need fixing, else sum = sum + divD
    // When dividend < 0, if sum <= 0, don't need fixing, else sum = sum - divD
    private val csaSum  = Mux(io.negX, ~io.sum, io.sum) + Mux(io.negX, ~io.carry, io.carry) + Mux(io.negX, U(15), U(0))
    private val rem     = csaSum
    private val fixSign = rem + Mux(io.negX, ~D, D)
    private val fixed   = RegNext(fixSign.asSInt >> U(2))
    private val shifted = fixed |>> io.shiftR
    private val result  = shifted(32 - 1 downto 0).asUInt
    io.reminder := Mux(io.div0 | io.ALTB, io.dividend, Mux(io.overflow, U(0), result))
  }
  // Quotient
  private val quotient = new Area {
    private val pre    = Mux(negR, conv.io.qm, conv.io.q)
    private val negQ   = io.negX ^ io.negD
    private val fixQ   = Mux(negQ, ~pre, pre) + Mux(negQ, 1, 0)
    private val result = RegNext(fixQ)
    private val neg1   = U"1'b1" @* 32
    io.quotient := Mux(io.div0, neg1, Mux(io.overflow, io.dividend, Mux(io.ALTB, U(0), result)))
  }
}
