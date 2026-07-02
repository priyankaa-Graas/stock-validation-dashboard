import unittest
import pandas as pd
import numpy as np
from validator import clean_sku, StockResolver, evaluate_sku_logic, validate_lazada, validate_shopee, validate_tiktok

class TestStockValidator(unittest.TestCase):
    def test_clean_sku(self):
        self.assertEqual(clean_sku("  A  "), "A")
        self.assertEqual(clean_sku("12345.0"), "12345")
        self.assertEqual(clean_sku("12345"), "12345")
        self.assertEqual(clean_sku(np.nan), "")
        self.assertEqual(clean_sku(None), "")

    def test_stock_resolver(self):
        # Create a mock All File dataframe
        all_data = pd.DataFrame({
            'sellerSKU': ['A', 'B', 'C', '10023.0'],
            'TC Stock': [100, 50, 15, '20'],
            'Reserved Stock': [10, 5, 2, '0']
        })
        resolver = StockResolver(all_data)
        
        # Test base lookup
        self.assertEqual(resolver.get_tc_stock('A'), 100)
        self.assertEqual(resolver.get_tc_stock('B'), 50)
        self.assertEqual(resolver.get_tc_stock('10023'), 20)
        self.assertEqual(resolver.get_tc_stock('D'), 0) # Missing SKU
        
        # Test '+' bundle (e.g. A+B)
        self.assertEqual(resolver.get_tc_stock('A+B'), 50) # min(100, 50)
        self.assertEqual(resolver.get_tc_stock('A+B+C'), 15) # min(100, 50, 15)
        
        # Test 'X' bundle (e.g. AX2, BX3)
        self.assertEqual(resolver.get_tc_stock('AX2'), 50) # 100 // 2
        self.assertEqual(resolver.get_tc_stock('BX3'), 16) # 50 // 3 = 16
        
        # Test combination bundle (e.g. (A+B)X2)
        # Note: A+B stock is 50, so (A+B)X2 should be 50 // 2 = 25
        # Wait, since my code splits '+' first, let's see:
        # get_tc_stock('AX2+BX2'): 'AX2' is 50, 'BX2' is 25. min(50, 25) = 25.
        # Let's verify 'AX2+BX2'
        self.assertEqual(resolver.get_tc_stock('AX2+BX2'), 25)

    def test_evaluate_sku_logic(self):
        # Case 1: Status Check = True, Stock Check = True -> All Good
        status_chk, stock_chk, action = evaluate_sku_logic(
            mp_status='Active', tc_status='Active', mp_stock=10, tc_stock=10, reserved_stock=0, max_0='No'
        )
        self.assertTrue(status_chk)
        self.assertTrue(stock_chk)
        self.assertEqual(action, "All Good")

        # Case 2: Status Check = False, Stock Check = True, Stock = 0 -> Change to inactive
        status_chk, stock_chk, action = evaluate_sku_logic(
            mp_status='Active', tc_status='Inactive', mp_stock=0, tc_stock=0, reserved_stock=0, max_0='No'
        )
        self.assertFalse(status_chk)
        self.assertTrue(stock_chk)
        self.assertEqual(action, "Change to inactive")

        # Case 3: Status Check = False, Stock Check = True, Stock > 1, Max = Yes -> Change to inactive
        status_chk, stock_chk, action = evaluate_sku_logic(
            mp_status='Active', tc_status='Inactive', mp_stock=5, tc_stock=5, reserved_stock=0, max_0='Yes'
        )
        self.assertFalse(status_chk)
        self.assertTrue(stock_chk)
        self.assertEqual(action, "Change to inactive")

        # Case 4: Status Check = False, Stock Check = True, Stock > 1, Max = No -> Change to active
        status_chk, stock_chk, action = evaluate_sku_logic(
            mp_status='Inactive', tc_status='Active', mp_stock=5, tc_stock=5, reserved_stock=0, max_0='No'
        )
        self.assertFalse(status_chk)
        self.assertTrue(stock_chk)
        self.assertEqual(action, "Change to active")

        # Case 5: Status Check = True, Stock Check = False, Max = Yes -> Max Already Done
        status_chk, stock_chk, action = evaluate_sku_logic(
            mp_status='Active', tc_status='Active', mp_stock=10, tc_stock=5, reserved_stock=0, max_0='Yes'
        )
        self.assertTrue(status_chk)
        self.assertFalse(stock_chk)
        self.assertEqual(action, "Max Already Done")

        # Case 6: Status Check = True, Stock Check = False, Max = No, Reserved > 0 -> Reserved Done
        status_chk, stock_chk, action = evaluate_sku_logic(
            mp_status='Active', tc_status='Active', mp_stock=10, tc_stock=5, reserved_stock=2, max_0='No'
        )
        self.assertTrue(status_chk)
        self.assertFalse(stock_chk)
        self.assertEqual(action, "Reserved Done")

        # Case 7: Status Check = True, Stock Check = False, Max = No, Reserved <= 0, Buffer > 0 -> Buffer Done
        # Buffer = TC - MP. So TC=15, MP=10 -> Buffer=5 > 0.
        status_chk, stock_chk, action = evaluate_sku_logic(
            mp_status='Active', tc_status='Active', mp_stock=10, tc_stock=15, reserved_stock=0, max_0='No'
        )
        self.assertTrue(status_chk)
        self.assertFalse(stock_chk)
        self.assertEqual(action, "Buffer Done")

        # Case 8: Status Check = True, Stock Check = False, Max = No, Reserved <= 0, Buffer < 0 -> Impact/Force Stock Push
        # Buffer = TC - MP. So TC=5, MP=10 -> Buffer=-5 < 0.
        status_chk, stock_chk, action = evaluate_sku_logic(
            mp_status='Active', tc_status='Active', mp_stock=10, tc_stock=5, reserved_stock=0, max_0='No'
        )
        self.assertTrue(status_chk)
        self.assertFalse(stock_chk)
        self.assertEqual(action, "Impact/Force Stock Push")

if __name__ == '__main__':
    unittest.main()
