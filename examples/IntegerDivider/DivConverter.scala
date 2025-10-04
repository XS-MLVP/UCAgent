/*
 * Module: On-the-Fly convertor
 * Author: wangjunyue2001@gmail.com
 * Description:
 *  This module will convert redundant representations to the conventional, Reference from:
 *  Ercegovac and Lang, “On-the-Fly Conversion of Redundant into Conventional Representations,” IEEE Transactions on Computers, vol. C–36, no. 7, pp. 895–897, July 1987, doi: 10.1109/TC.1987.1676986.
 */

package divider

import spinal.core._

import scala.language.postfixOps

case class DivConverter() extends Module {
  /* On-the-Fly Convertor of Redundant to Conventional Representations */
  val io = new Bundle {
    val valid = in Bool ()
    val qsm   = in UInt (4 bits)   // 4-bits quotient select (one hot) mask
    val q     = out UInt (32 bits) // Q in 2's complement form
    val qm    = out UInt (32 bits) // Q - 1
  }
  /* The sign bit in true form */
  private val s = io.qsm(1) | io.qsm(0) // -2, -1
  /* The value field in true form */
  private val m1 = io.qsm(3) | io.qsm(0) // 2, -2
  private val m0 = io.qsm(2) | io.qsm(1) // 1, -1
  /* Convert bits */
  private val a = (s | m1) ## m0
  private val b = (~m1 & (~m0 | s)) ## ~m0
  /* Control logics */
  private val shiftA = !s
  private val shiftB = s | (~m0 & ~m1)
  private val loadA  = !shiftA // s
  private val loadB  = !shiftB
  /* Convert registers */
  private val A = Reg(UInt(32 bits))
  private val B = Reg(UInt(32 bits))
  /* Register behaviour */
  private val lowA  = A(32 - 3 downto 0).asBits
  private val lowB  = B(32 - 3 downto 0).asBits
  private val fullA = Mux(loadA, lowB, lowA) ## a
  private val fullB = Mux(loadB, lowA, lowB) ## b
  private val nextA = fullA(32 - 1 downto 0).asUInt
  private val nextB = fullB(32 - 1 downto 0).asUInt
  when(io.valid) {
    A := U(0)
    B := U(0)
  }.otherwise {
    A := nextA
    B := nextB
  }
  /* Output result */
  io.q  := A
  io.qm := B
}
