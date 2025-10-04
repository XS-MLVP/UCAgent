/*
 * Module: PreProcess
 * Author: wangjunyue2001@gmail.com
 * Description: Initialization of the division operation, including normalization steps.
 */

package divider

import spinal.core._
import spinal.lib.CountLeadingZeroes

import scala.language.postfixOps

case class PreProcess() extends Module {
  val io = new Bundle {
    val valid    = in Bool ()
    val signed   = in Bool ()
    val dividend = in UInt (32 bits)
    val divisor  = in UInt (32 bits)
    val divX     = out UInt (36 bits) // Absolute dividend
    val divD     = out UInt (36 bits) // Normalized absolute divisor
    val negX     = out Bool ()        // Dividend is negative
    val negD     = out Bool ()        // Divisor is negative
    val shiftR   = out UInt (6 bits)
    val cycle    = out UInt (5 bits)
    // Special case
    val special  = out Bool ()
    val div0     = out Bool () // Divisor is zero
    val ALTB     = out Bool ()
    val overflow = out Bool () // Overflow: The most-negative integer is divided by -1
  }
  // 32 bits dividend & divisor are called "A & B", above 33 bits called "X & Y"
  private val divA  = io.dividend
  private val divB  = io.divisor
  private val negA  = io.signed & io.dividend.msb
  private val negB  = io.signed & io.divisor.msb
  private val posA  = Mux(negA, ~divA, divA) + Mux(negA, 1, 0)
  private val posB  = Mux(negB, ~divB, divB) + Mux(negB, 1, 0)
  private val ifX   = posA @@ U"1'b0"
  private val ifD   = posB @@ U"1'b0"
  private val lzcA  = CountLeadingZeroes(posA.asBits)
  private val lzcB  = CountLeadingZeroes(posB.asBits)
  private val lzcX  = lzcA(log2Up(32) - 1 downto 0)
  private val lzcD  = lzcB(log2Up(32) - 1 downto 0)
  private val normX = ifX |<< lzcX
  private val normD = ifD |<< lzcD
  // normD
  private val divD = RegNextWhen(normD, io.valid)
  io.divD := divD.resized
  private val negD = negB
  io.negD := negD
  // Div cycle
  private val zeroDiff = lzcD - lzcX
  private val ALTB     = lzcD < lzcX
  private val resBits  = U(1) +^ Mux(ALTB, U(0), zeroDiff)
  private val cycle    = resBits(resBits.getWidth - 1 downto 1) + 1 // Should cost (resBits / 2 + 1) cycles
  io.cycle := cycle
  io.ALTB  := RegNext(ALTB)
  // normX
  private val divX        = U"3'b0" @@ normX
  private val rightShiftX = U(!resBits.lsb)
  private val divXShifted = divX |>> rightShiftX
  io.divX := divXShifted
  private val negX = negA
  io.negX := negX
  // Normalized shift
  private val shift  = lzcD +^ 1
  private val shiftR = RegNextWhen(shift, io.valid)
  io.shiftR := shiftR
  // Div0
  private val div0 = !(io.divisor.orR)
  io.div0 := div0
  // Overflow
  private val minX     = io.dividend.msb && !(io.dividend(32 - 2 downto 0).orR)
  private val overflow = io.signed && minX && io.divisor.andR
  io.overflow := overflow
  // Special
  io.special := ALTB | div0 | overflow
}
