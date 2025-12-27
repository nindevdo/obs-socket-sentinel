#!/bin/bash

echo "🔍 Three.js Intro System Verification"
echo "======================================"
echo ""

# 1. Check backend
echo "1. Testing Backend..."
response=$(curl -s -X POST http://ss.nindevdo.com/action \
  -H "Authorization: Bearer rematch_garage_culinary_unluckily_unclamped_expansive" \
  -H "Content-Type: application/json" \
  -d '{"game":"hunt_showdown","action":"intro"}')

if echo "$response" | grep -q "success"; then
  echo "   ✅ Backend accepted intro action"
else
  echo "   ❌ Backend error: $response"
  exit 1
fi

# 2. Check overlay API
echo ""
echo "2. Checking Overlay API Response..."
sleep 0.5
overlay=$(curl -s http://ss.nindevdo.com/overlay)

if echo "$overlay" | grep -q '"intro"'; then
  if echo "$overlay" | grep -q '"trigger": true'; then
    echo "   ✅ Intro data present in overlay API"
    remaining=$(echo "$overlay" | python3 -c "import sys,json; data=json.load(sys.stdin); print(data.get('intro',{}).get('remaining_time','N/A'))" 2>/dev/null)
    echo "   ⏱️  Remaining time: ${remaining}s"
  else
    echo "   ⚠️  Intro present but not triggered (may have expired)"
  fi
else
  echo "   ❌ Intro not found in overlay response"
  exit 1
fi

# 3. Check HTML has Three.js
echo ""
echo "3. Checking HTML Template..."
html=$(curl -s http://ss.nindevdo.com/)

if echo "$html" | grep -q "three.js"; then
  echo "   ✅ Three.js library included in HTML"
else
  echo "   ❌ Three.js library NOT found in HTML"
  exit 1
fi

if echo "$html" | grep -q "intro-canvas"; then
  echo "   ✅ Intro canvas element found"
else
  echo "   ❌ Intro canvas element NOT found"
  exit 1
fi

if echo "$html" | grep -q "showIntro"; then
  echo "   ✅ showIntro() function found"
else
  echo "   ❌ showIntro() function NOT found"
  exit 1
fi

echo ""
echo "======================================"
echo "✅ ALL CHECKS PASSED!"
echo ""
echo "📝 Next Steps:"
echo "   1. Refresh your OBS Browser Source"
echo "      (Right-click → Refresh cache of current page)"
echo ""
echo "   2. Or test in regular browser:"
echo "      Open: http://ss.nindevdo.com/"
echo "      Then run: ./app/test_intro.sh"
echo ""
echo "   3. You should see:"
echo "      - 3D text 'The Cam Bros'"
echo "      - Fire particles animation"
echo "      - Rotating and glowing effects"
echo ""
