/*
 * Module: DivStage
 * Author: wangjunyue2001@gmail.com
 * Description:
 *  Iterative stage for radix-4 SRT division that selects quotient digits,
 *  performs CSA operations, and updates partial remainder in carry-save form.
 */

package divider

import divider.CarrySaveAdder
import spinal.core._

import scala.language.postfixOps

case class DivStage() extends Module {
  val io = new Bundle {
    val valid = in Bool ()
    val divX  = in UInt (36 bits)
    val divD  = in UInt (36 bits)
    val sum   = out UInt (36 bits)
    val carry = out UInt (36 bits)
    val qsm   = out UInt (4 bits)
  }
  private val qsm     = UInt(4 bits) // Q select (one hot) mask
  private val pSum    = Reg(UInt(36 bits))
  private val pCarry  = Reg(UInt(36 bits))
  private val msBitsD = io.divD(32 - 1 downto 32 - 3)
  private val msBitsS = pSum(36 - 1 downto 36 - 8)
  private val msBitsC = pCarry(36 - 1 downto 36 - 8)
  io.sum   := pSum
  io.carry := pCarry
  io.qsm   := qsm
  // Get q select mask
  private val st = SelectTable()
  st.io.sum   := msBitsS
  st.io.carry := msBitsC
  st.io.divD  := msBitsD
  qsm         := st.io.qsm
  // Get next values
  private val carryIn = qsm(3) | qsm(2)
  private val divD    = io.divD
  private val divD2   = io.divD |<< 1
  private val negD    = ~divD
  private val negD2   = ~divD2
  private val addIn = qsm.mux(
    U"4'b1000" -> negD2, // -2d
    U"4'b0100" -> negD,  // -d
    U"4'b0010" -> divD,  // +d
    U"4'b0001" -> divD2, // +2d
    default    -> U(0)
  )
  private val csa = CarrySaveAdder(36)
  csa.io.x   := pSum
  csa.io.y   := pCarry
  csa.io.z   := addIn
  csa.io.cin := carryIn
  when(io.valid) {
    pSum   := io.divX
    pCarry := U(0)
  }.otherwise {
    pSum   := csa.io.sum |<< 2
    pCarry := csa.io.cout |<< 2
  }
}
